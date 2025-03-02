import json
import os
import time
import requests
import re
from collections import defaultdict
from flask import Flask, request, Response, jsonify, redirect
from flask_cors import CORS
from urllib.parse import urlparse, urljoin, quote, unquote

# Inizializzazione dell'app Flask
app = Flask(__name__)
CORS(app)  # Abilita CORS per tutti gli endpoint

# Configurazione dell'addon
ADDON_NAME = "Vavoo.to Italy"
ADDON_ID = "com.stremio.vavoo.italy"
ADDON_VERSION = "1.0.1"
VAVOO_API_URL = "https://vavoo.to/channels"
VAVOO_STREAM_BASE_URL = "https://vavoo.to/play/{id}/index.m3u8"

# Configurazione del proxy
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to"
}

# Cache dei canali
channels_cache = []
cache_timestamp = 0
CACHE_DURATION = 600  # 10 minuti

# Funzione per normalizzare i nomi dei canali (rimuove numeri tra parentesi)
def normalize_channel_name(name):
    return re.sub(r"\s*\d+$", "", name).strip()

# Funzione per caricare e raggruppare i canali italiani
def load_italian_channels():
    global channels_cache, cache_timestamp
    current_time = time.time()

    if channels_cache and current_time - cache_timestamp < CACHE_DURATION:
        return channels_cache

    try:
        response = requests.get(VAVOO_API_URL, headers=DEFAULT_HEADERS)
        response.raise_for_status()

        all_channels = response.json()
        italian_channels = [ch for ch in all_channels if ch.get("country") == "Italy"]

        grouped_channels = defaultdict(list)

        for channel in italian_channels:
            normalized_name = normalize_channel_name(channel["name"])
            grouped_channels[normalized_name].append(channel)

        unified_channels = []
        for name, channels in grouped_channels.items():
            main_channel = channels[0]
            main_channel["streams"] = [{"id": ch["id"], "url": VAVOO_STREAM_BASE_URL.format(id=ch["id"])} for ch in channels]
            unified_channels.append(main_channel)

        channels_cache = unified_channels
        cache_timestamp = current_time

        return unified_channels
    except Exception as e:
        print(f"Errore nel caricamento dei canali: {str(e)}")
        return channels_cache if channels_cache else []

# Funzione per determinare il genere del canale
def get_channel_genre(channel_name):
    channel_name = channel_name.lower()
    
    genres = {
        "SPORT": ["sport", "calcio", "football", "tennis", "basket", "motogp", "f1", "golf"],
        "NEWS": ["news", "tg", "24", "meteo", "giornale", "notizie"],
        "KIDS": ["kids", "bambini", "cartoon", "disney", "nick", "boing", "junior"],
        "MOVIES": ["cinema", "film", "movie", "premium", "comedy"],
        "DOCUMENTARIES": ["discovery", "history", "national", "geo", "natura", "science"],
        "MUSIC": ["music", "mtv", "vh1", "radio", "hit", "rock"]
    }
    
    for genre, keywords in genres.items():
        for keyword in keywords:
            if keyword in channel_name:
                return genre
    
    return "GENERAL"

# Endpoint manifest.json per Stremio
@app.route('/manifest.json', methods=['GET'])
def manifest_json():
    base_url = request.url_root.rstrip('/')
    manifest = {
        "id": ADDON_ID,
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Canali italiani da vavoo.to",
        "resources": ["catalog", "meta", "stream"],
        "types": ["tv"],
        "catalogs": [
            {
                "type": "tv",
                "id": "vavoo_italy",
                "name": "Vavoo.to Italia",
                "extra": [{"name": "search", "isRequired": False}]
            }
        ],
        "behaviorHints": {
            "configurable": False,
            "configurationRequired": False
        },
        "logo": "https://vavoo.to/favicon.ico",
        "background": "https://via.placeholder.com/1280x720/000080/FFFFFF?text=Vavoo.to%20Italia"
    }
    return jsonify(manifest)

# Endpoint per il catalogo
@app.route('/catalog/<type>/<id>.json', methods=['GET'])
def catalog(type, id):
    if type != "tv" or id != "vavoo_italy":
        return jsonify({"metas": []})

    search = request.args.get('search', '')
    skip = int(request.args.get('skip', 0))
    return get_catalog_response(type, id, search, skip)

def get_catalog_response(type, id, search, skip):
    channels = load_italian_channels()

    if search:
        search = search.lower()
        channels = [ch for ch in channels if search in ch["name"].lower()]

    channels = channels[skip:skip+100]

    metas = []
    for channel in channels:
        genre = get_channel_genre(channel["name"])

        metas.append({
            "id": str(channel["streams"][0]["id"]),
            "type": "tv",
            "name": channel["name"],
            "genres": [genre],
            "poster": f"https://placehold.co/300x300?text={quote(channel['name'])}",
            "posterShape": "square",
            "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}"
        })

    return jsonify({"metas": metas})

# Endpoint per ottenere gli stream di un canale
@app.route('/stream/<type>/<channel_id>.json', methods=['GET'])
def stream(type, channel_id):
    if type != "tv":
        return jsonify({"streams": []})

    channels = load_italian_channels()
    
    for channel in channels:
        for stream in channel.get("streams", []):
            if str(stream["id"]) == channel_id:
                channel_name = channel["name"]
                streams = [
                    {
                        "url": f"/proxy/m3u?url={quote(stream['url'])}",
                        "title": f"{channel_name} - Stream {i+1}",
                        "name": "Vavoo.to"
                    }
                    for i, stream in enumerate(channel["streams"])
                ]
                return jsonify({"streams": streams})

    return jsonify({"streams": []})

# Endpoint per il proxy M3U
@app.route('/proxy/m3u')
def proxy_m3u():
    m3u_url = request.args.get('url', '').strip()
    if not m3u_url:
        return "Errore: Parametro 'url' mancante", 400

    try:
        response = requests.get(m3u_url, headers=DEFAULT_HEADERS, allow_redirects=True)
        response.raise_for_status()
        return Response(response.text, content_type="application/vnd.apple.mpegurl")
    except requests.RequestException as e:
        return f"Errore: {str(e)}", 500

# Pagina di installazione
@app.route('/install')
def install_instructions():
    return f'<h1>Installa l\'addon su Stremio</h1><p>URL: {request.url_root.rstrip("/")}/manifest.json</p>'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
