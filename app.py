import json
import os
import requests
from flask import Flask, request, Response, jsonify
from urllib.parse import urlparse, urljoin, quote, unquote

# Inizializzazione dell'app Flask
app = Flask(__name__)

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

# Endpoint per il manifest dell'addon
@app.route('/', methods=['GET'])
def addon_manifest():
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
                "extra": [{"name": "skip", "options": ["0", "100", "200"]}]
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
    
    return jsonify(manifest)

# Funzione per caricare e filtrare i canali italiani da vavoo.to
def load_italian_channels():
    try:
        response = requests.get(VAVOO_API_URL, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        
        all_channels = response.json()
        italian_channels = [ch for ch in all_channels if ch.get("country") == "Italy"]
        
        return italian_channels
    except Exception as e:
        print(f"Errore nel caricamento dei canali: {str(e)}")
        return []

# Endpoint per il catalogo (formato standard Stremio)
@app.route('/catalog/<type>/<id>.json', methods=['GET'])
def catalog(type, id):
    # Controlliamo che il tipo e id corrispondano a quelli supportati
    if type != "tv" or id != "vavoo_italy":
        return jsonify({"metas": []})
    skip = int(request.args.get('skip', 0))
    
    channels = load_italian_channels()
    channels = channels[skip:skip+100]  # Paginazione
    
    metas = []
    for channel in channels:
        metas.append({
            "id": str(channel["id"]),
            "type": "tv",
            "name": channel["name"],
            "poster": f"https://via.placeholder.com/300x450/0000FF/FFFFFF?text={quote(channel['name'])}",
            "posterShape": "regular",
            "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}"
        })
    
    return jsonify({"metas": metas})

# Endpoint per i meta (formato standard Stremio)
@app.route('/meta/<type>/<channel_id>.json', methods=['GET'])
def meta(type, channel_id):
    # Controlliamo che il tipo sia supportato
    if type != "tv":
        return jsonify({"error": "Tipo non supportato"}), 404
    channels = load_italian_channels()
    channel = next((ch for ch in channels if str(ch["id"]) == channel_id), None)
    
    if not channel:
        return jsonify({"error": "Canale non trovato"}), 404
    
    meta = {
        "id": str(channel["id"]),
        "type": "tv",
        "name": channel["name"],
        "poster": f"https://via.placeholder.com/300x450/0000FF/FFFFFF?text={quote(channel['name'])}",
        "posterShape": "regular",
        "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}",
        "videos": [
            {
                "id": str(channel["id"]),
                "title": channel["name"],
                "released": "Live Stream",
                "streams": [{"url": ""}]  # Stremio caricherà gli stream dall'endpoint stream
            }
        ]
    }
    
    return jsonify(meta)

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
    
    # Restituisci l'oggetto stream per Stremio
    return jsonify({
        "streams": [
            {
                "url": proxied_url,
                "title": "Vavoo.to Stream",
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

# Supporto per il manifest.json specifico (formato richiesto da Stremio)
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
                "extra": [{"name": "skip", "options": ["0", "100", "200"]}]
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

# Istruzioni per l'installazione dell'addon su Stremio
@app.route('/install')
def install_instructions():
    base_url = request.url_root.rstrip('/')
    stremio_url = f"stremio://app.strem.io/addon/{base_url}/manifest.json"
    
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
        <code>{base_url}</code>
    </body>
    </html>
    """
    
    return html

if __name__ == '__main__':
    # Configurazione per l'ambiente di produzione
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
