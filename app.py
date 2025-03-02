import json
import os
import time
import requests
from flask import Flask, request, Response, jsonify, redirect
from flask_cors import CORS
from urllib.parse import urlparse, urljoin, quote, unquote

# Inizializzazione dell'app Flask
app = Flask(__name__)
CORS(app)  # Abilita CORS per tutti gli endpoint

# Configurazione dell'addon
ADDON_NAME = "Vavoo.to Italy"
ADDON_ID = "com.stremio.vavoo.italy"
ADDON_VERSION = "1.0.0"
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
CACHE_DURATION = 3600  # 1 ora in secondi

# Carica il file JSON dei loghi
def load_logos():
    try:
        # Percorso al file JSON nella stessa directory dello script
        logos_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'canali_con_loghi_finale.json')
        
        with open(logos_file_path, 'r', encoding='utf-8') as file:
            logos_data = json.load(file)
        
        # Crea un dizionario senza normalizzare i nomi
        logos_dict = {}
        for channel in logos_data:
            if "name" in channel:
                # Usa il nome esatto del canale come chiave
                logos_dict[channel["name"]] = channel.get("logo", "")
        
        return logos_dict
    except Exception as e:
        print(f"Errore nel caricamento dei loghi: {str(e)}")
        return {}

# Carica i loghi all'avvio dell'applicazione
channel_logos = load_logos()

# Funzione per trovare il logo corrispondente a un canale con confronto diretto
def find_logo_for_channel(channel_name):
    # Accedi alla variabile globale
    global channel_logos
    
    # Cerca una corrispondenza esatta senza normalizzazione
    if channel_name in channel_logos:
        return channel_logos[channel_name]
    
    # Se non viene trovato un logo, restituisci un URL di placeholder
    return f"https://placehold.co/300x300?text={quote(channel_name)}&.jpg"

# Funzione per caricare e filtrare i canali italiani da vavoo.to
def load_italian_channels():
    global channels_cache, cache_timestamp
    current_time = time.time()
    
    # Usa la cache se disponibile e non scaduta
    if channels_cache and current_time - cache_timestamp < CACHE_DURATION:
        return channels_cache
    
    try:
        response = requests.get(VAVOO_API_URL, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        
        all_channels = response.json()
        italian_channels = [ch for ch in all_channels if ch.get("country") == "Italy"]
        
        # Aggiorna la cache
        channels_cache = italian_channels
        cache_timestamp = current_time
        
        return italian_channels
    except Exception as e:
        print(f"Errore nel caricamento dei canali: {str(e)}")
        return channels_cache if channels_cache else []

def get_channel_genre(channel_name):
    """Determina il genere del canale in base al nome"""
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

# Supporto per il manifest.json specifico (formato richiesto da Stremio)
@app.route('/manifest.json', methods=['GET'])
def manifest_json():
    # Assicuriamoci che l'URL base usi HTTPS
    if request.headers.get('X-Forwarded-Proto') == 'https':
        base_url = 'https://' + request.host
    else:
        base_url = request.url_root.rstrip('/')
        # Se non siamo sicuri che sia HTTPS, forziamo HTTPS per gli ambienti di produzione
        if not base_url.startswith('http://localhost') and not base_url.startswith('https://'):
            base_url = 'https://' + request.host
    
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
        "background": "https://via.placeholder.com/1280x720/000080/FFFFFF?text=Vavoo.to%20Italia",
        "contactEmail": "example@example.com"  # Sostituire con email reale se necessario
    }
    
    # Assicuriamoci che i content-type siano corretti
    response = jsonify(manifest)
    response.headers['Content-Type'] = 'application/json'
    return response

@app.route('/', methods=['GET'])
def root():
    """Reindirizzamento alla pagina di installazione"""
    return redirect('/install')

# Endpoint per il catalogo (formato standard Stremio)
@app.route('/catalog/<type>/<id>.json', methods=['GET'])
def catalog(type, id):
    # Controlliamo che il tipo e id corrispondano a quelli supportati
    if type != "tv" or id != "vavoo_italy":
        return jsonify({"metas": []})
        
    search = request.args.get('search', '')
    skip = int(request.args.get('skip', 0))
    
    return get_catalog_response(type, id, search, skip)

# Endpoint per il catalogo con parametro search nel percorso (formato Stremio)
@app.route('/catalog/<type>/<id>/<extra>.json', methods=['GET'])
def catalog_with_extra(type, id, extra):
    # Controlliamo che il tipo e id corrispondano a quelli supportati
    if type != "tv" or id != "vavoo_italy":
        return jsonify({"metas": []})
    
    search = ""
    skip = 0
    
    # Parsing dei parametri extra
    if extra.startswith("search="):
        search = extra.split("=", 1)[1]
    elif extra.startswith("skip="):
        try:
            skip = int(extra.split("=", 1)[1])
        except ValueError:
            skip = 0
    
    return get_catalog_response(type, id, search, skip)

def get_catalog_response(type, id, search, skip):
    channels = load_italian_channels()
    
    # Filtra per la ricerca se specificata
    if search:
        search = search.lower()
        channels = [ch for ch in channels if search in ch["name"].lower()]
    
    # Applica paginazione
    channels = channels[skip:skip+100]
    
    metas = []
    for channel in channels:
        genre = get_channel_genre(channel["name"])
        # Trova il logo appropriato per il canale
        logo_url = find_logo_for_channel(channel["name"])
        
        metas.append({
            "id": str(channel["id"]),
            "type": "tv",
            "name": channel["name"],
            "genres": [genre],
            "poster": logo_url,  # Usa il logo del canale come poster
            "posterShape": "square",
            "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}",
            "logo": logo_url  # Usa lo stesso logo come icona del canale
        })
    
    return jsonify({"metas": metas})

# Endpoint per i meta (formato standard Stremio)
@app.route('/meta/<type>/<channel_id>.json', methods=['GET'])
def meta(type, channel_id):
    # Controlliamo che il tipo sia supportato
    if type != "tv":
        return jsonify({"meta": None})
        
    channels = load_italian_channels()
    channel = next((ch for ch in channels if str(ch["id"]) == channel_id), None)
    
    if not channel:
        return jsonify({"meta": None})
    
    genre = get_channel_genre(channel["name"])
    logo_url = find_logo_for_channel(channel["name"])
    
    meta_obj = {
        "id": str(channel["id"]),
        "type": "tv",
        "name": channel["name"],
        "genres": [genre],
        "poster": logo_url,
        "posterShape": "square",
        "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}",
        "logo": logo_url
    }
    
    return jsonify({"meta": meta_obj})

# Endpoint per lo stream (formato standard Stremio)
@app.route('/stream/<type>/<channel_id>.json', methods=['GET'])
def stream(type, channel_id):
    # Controlliamo che il tipo sia supportato
    if type != "tv":
        return jsonify({"streams": []})
    
    # Costruisci l'URL dello stream
    stream_url = VAVOO_STREAM_BASE_URL.format(id=channel_id)
    
    # Costruisci l'URL del proxy con HTTPS
    if request.headers.get('X-Forwarded-Proto') == 'https':
        base_url = 'https://' + request.host
    else:
        base_url = request.url_root.rstrip('/')
        # Se non siamo sicuri che sia HTTPS, forziamo HTTPS per gli ambienti di produzione
        if not base_url.startswith('http://localhost') and not base_url.startswith('https://'):
            base_url = 'https://' + request.host
            
    headers_str = "&".join([f"header_{quote(k)}={quote(v)}" for k, v in DEFAULT_HEADERS.items()])
    proxied_url = f"{base_url}/proxy/m3u?url={quote(stream_url)}&{headers_str}"
    
    channels = load_italian_channels()
    channel = next((ch for ch in channels if str(ch["id"]) == channel_id), None)
    channel_name = channel["name"] if channel else "Unknown"
    
    # Restituisci l'oggetto stream per Stremio
    return jsonify({
        "streams": [
            {
                "url": proxied_url,
                "title": f"{channel_name} - Vavoo.to Stream",
                "name": "Vavoo.to"
            }
        ]
    })

# Funzione per rilevare il tipo di m3u
def detect_m3u_type(content):
    """ Rileva se è un M3U (lista IPTV) o un M3U8 (flusso HLS) """
    if "#EXTM3U" in content and "#EXTINF" in content:
        return "m3u8"
    return "m3u"

# Endpoint per il proxy m3u
@app.route('/proxy/m3u')
def proxy_m3u():
    """ Proxy per file M3U e M3U8 con supporto per redirezioni e header personalizzati """
    m3u_url = request.args.get('url', '').strip()
    if not m3u_url:
        return "Errore: Parametro 'url' mancante", 400

    # Headers di default per evitare blocchi del server
    headers = {**DEFAULT_HEADERS, **{
        unquote(key[7:]).replace("_", "-"): unquote(value).strip()
        for key, value in request.args.items()
        if key.lower().startswith("header_")
    }}

    try:
        response = requests.get(m3u_url, headers=headers, allow_redirects=True)
        response.raise_for_status()
        final_url = response.url  
        m3u_content = response.text

        file_type = detect_m3u_type(m3u_content)

        if file_type == "m3u":
            return Response(m3u_content, content_type="audio/x-mpegurl")

        parsed_url = urlparse(final_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.rsplit('/', 1)[0]}/"

        headers_query = "&".join([f"header_{quote(k)}={quote(v)}" for k, v in headers.items()])

        modified_m3u8 = []
        for line in m3u_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                segment_url = urljoin(base_url, line)  
                # Manteniamo il path relativo per il proxy ts
                proxied_url = f"/proxy/ts?url={quote(segment_url)}&{headers_query}"
                modified_m3u8.append(proxied_url)
            else:
                modified_m3u8.append(line)

        modified_m3u8_content = "\n".join(modified_m3u8)
        return Response(modified_m3u8_content, content_type="application/vnd.apple.mpegurl")

    except requests.RequestException as e:
        return f"Errore durante il download del file M3U/M3U8: {str(e)}", 500

# Endpoint per il proxy ts
@app.route('/proxy/ts')
def proxy_ts():
    """ Proxy per segmenti .TS con headers personalizzati e gestione dei redirect """
    ts_url = request.args.get('url', '').strip()
    if not ts_url:
        return "Errore: Parametro 'url' mancante", 400

    headers = {
        unquote(key[7:]).replace("_", "-"): unquote(value).strip()
        for key, value in request.args.items()
        if key.lower().startswith("header_")
    }

    try:
        response = requests.get(ts_url, headers=headers, stream=True, allow_redirects=True)
        response.raise_for_status()
        return Response(response.iter_content(chunk_size=1024), content_type="video/mp2t")
    
    except requests.RequestException as e:
        return f"Errore durante il download del segmento TS: {str(e)}", 500

# Istruzioni per l'installazione dell'addon su Stremio
@app.route('/install')
def install_instructions():
    # Assicuriamoci che l'URL di installazione sia HTTPS
    if request.headers.get('X-Forwarded-Proto') == 'https':
        base_url = 'https://' + request.host
    else:
        base_url = request.url_root.rstrip('/')
        # Se non siamo su localhost, forzare HTTPS
        if not base_url.startswith('http://localhost') and not base_url.startswith('https://'):
            base_url = 'https://' + request.host
            
    stremio_url = f"stremio://{request.host}/manifest.json"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Installazione Vavoo.to Italia Addon</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
            .button {{ display: inline-block; background-color: #2196F3; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <h1>Vavoo.to Italia Addon per Stremio</h1>
        <p>Per installare l'addon, clicca sul pulsante qui sotto:</p>
        <a class="button" href="{stremio_url}">Installa su Stremio</a>
        <p>Oppure aggiungi manualmente questo URL in Stremio:</p>
        <code>{base_url}/manifest.json</code>
    </body>
    </html>
    """
    
    return html

@app.route('/status.json')
def status():
    """Endpoint per verificare lo stato dell'addon"""
    channels = load_italian_channels()
    
    # Aggiungi anche lo stato del caricamento dei loghi
    return jsonify({
        "status": "online",
        "channels_count": len(channels),
        "logos_count": len(channel_logos),
        "cache_timestamp": cache_timestamp,
        "cache_age_seconds": time.time() - cache_timestamp if cache_timestamp > 0 else 0,
        "version": ADDON_VERSION
    })

@app.route('/<path:invalid_path>')
def catch_all(invalid_path):
    """Gestisci percorsi non validi reindirizzando alla pagina di installazione"""
    return redirect('/install')

if __name__ == '__main__':
    # Configurazione per l'ambiente di produzione
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
