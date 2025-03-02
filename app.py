import json
import os
import time
import logging
import requests
from flask import Flask, request, Response, jsonify, redirect
from flask_cors import CORS
from urllib.parse import urlparse, urljoin, quote, unquote
import unicodedata
import re

# Configurazione del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('vavoo-addon')

# Inizializzazione dell'app Flask
app = Flask(__name__)
CORS(app)  # Abilita CORS per tutti gli endpoint

# Configurazione dell'addon
ADDON_NAME = "Vavoo.to Italy"
ADDON_ID = "com.stremio.vavoo.italy"
ADDON_VERSION = "1.1.0"
VAVOO_API_URL = "https://vavoo.to/channels"
VAVOO_STREAM_BASE_URL = "https://vavoo.to/play/{id}/index.m3u8"
ID_PREFIX = "vavoo_"  # Prefisso per gli ID dei contenuti

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
CACHE_LOGOS = {}  # Cache per i loghi
CACHE_LOGOS_TIMESTAMP = 0

# Funzione per normalizzare il testo (rimuovere accenti, minuscolo, ecc.)
def normalize_text(text):
    """
    Normalizza il testo per le ricerche (rimuove accenti, minuscolo, ecc.)
    """
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text)  # Rimuovi accenti
    return text.lower().strip()

# Carica il file JSON dei loghi
def load_logos():
    global CACHE_LOGOS, CACHE_LOGOS_TIMESTAMP
    current_time = time.time()
    
    # Usa la cache se disponibile e non scaduta
    if CACHE_LOGOS and current_time - CACHE_LOGOS_TIMESTAMP < CACHE_DURATION:
        return CACHE_LOGOS
    
    try:
        # Percorso al file JSON nella stessa directory dello script
        logos_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'canali_con_loghi_finale.json')
        
        with open(logos_file_path, 'r', encoding='utf-8') as file:
            logos_data = json.load(file)
        
        # Crea un dizionario con nome originale e nome normalizzato come chiavi
        logos_dict = {}
        for channel in logos_data:
            if "name" in channel:
                # Usa il nome esatto del canale come chiave
                logos_dict[channel["name"]] = channel.get("logo", "")
                # Usa anche il nome normalizzato per facilitare la ricerca
                logos_dict[normalize_text(channel["name"])] = channel.get("logo", "")
        
        # Aggiorna la cache
        CACHE_LOGOS = logos_dict
        CACHE_LOGOS_TIMESTAMP = current_time
        
        logger.info(f"Loghi caricati: {len(logos_dict)}")
        return logos_dict
    except Exception as e:
        logger.error(f"Errore nel caricamento dei loghi: {str(e)}")
        return CACHE_LOGOS if CACHE_LOGOS else {}

# Funzione per trovare il logo corrispondente a un canale
def find_logo_for_channel(channel_name):
    """
    Trova il logo corrispondente a un canale con vari metodi di confronto
    """
    # Accedi alla variabile globale
    logos = load_logos()
    
    # Cerca una corrispondenza esatta
    if channel_name in logos:
        return logos[channel_name]
    
    # Cerca una corrispondenza normalizzata
    norm_name = normalize_text(channel_name)
    if norm_name in logos:
        return logos[norm_name]
    
    # Se non viene trovato un logo, restituisci un URL di placeholder
    return f"https://placehold.co/300x300?text={quote(channel_name)}&.jpg"

# Funzione per caricare e filtrare i canali italiani da vavoo.to
def load_italian_channels():
    global channels_cache, cache_timestamp
    current_time = time.time()
    
    # Usa la cache se disponibile e non scaduta
    if channels_cache and current_time - cache_timestamp < CACHE_DURATION:
        logger.debug(f"Utilizzo cache canali ({len(channels_cache)} canali)")
        return channels_cache
    
    try:
        logger.info("Richiesta canali a vavoo.to API")
        response = requests.get(VAVOO_API_URL, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()
        
        all_channels = response.json()
        italian_channels = [ch for ch in all_channels if ch.get("country") == "Italy"]
        
        if not italian_channels:
            logger.warning("Nessun canale italiano trovato")
            return channels_cache if channels_cache else []
        
        # Aggiorna la cache
        channels_cache = italian_channels
        cache_timestamp = current_time
        
        logger.info(f"Canali italiani caricati: {len(italian_channels)}")
        return italian_channels
    except requests.Timeout:
        logger.error("Timeout nella richiesta dei canali")
        return channels_cache if channels_cache else []
    except requests.RequestException as e:
        logger.error(f"Errore nella richiesta dei canali: {str(e)}")
        return channels_cache if channels_cache else []
    except Exception as e:
        logger.error(f"Errore generico nel caricamento dei canali: {str(e)}")
        return channels_cache if channels_cache else []

def get_channel_genre(channel_name):
    """Determina il genere del canale in base al nome"""
    if not channel_name:
        return "GENERAL"
        
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

# Ottieni l'URL base con HTTPS quando possibile
def get_base_url():
    if request.headers.get('X-Forwarded-Proto') == 'https':
        base_url = 'https://' + request.host
    else:
        base_url = request.url_root.rstrip('/')
        # Se non siamo sicuri che sia HTTPS, forziamo HTTPS per gli ambienti di produzione
        if not base_url.startswith('http://localhost') and not base_url.startswith('https://'):
            base_url = 'https://' + request.host
    return base_url

# Supporto per il manifest.json specifico (formato richiesto da Stremio)
@app.route('/manifest.json', methods=['GET'])
def manifest_json():
    base_url = get_base_url()
    
    manifest = {
        "id": ADDON_ID,
        "version": ADDON_VERSION,
        "name": ADDON_NAME,
        "description": "Canali italiani da vavoo.to",
        "resources": [
            "catalog",
            {
                "name": "meta",
                "types": ["tv"],
                "idPrefixes": [ID_PREFIX]
            },
            {
                "name": "stream",
                "types": ["tv"],
                "idPrefixes": [ID_PREFIX]
            }
        ],
        "types": ["tv"],
        "catalogs": [
            {
                "type": "tv", 
                "id": "vavoo_italy",
                "name": "Vavoo.to Italia",
                "extra": [
                    {"name": "search", "isRequired": False},
                    {"name": "genre", "isRequired": False},
                    {"name": "skip", "isRequired": False}
                ],
                "genres": ["SPORT", "NEWS", "KIDS", "MOVIES", "DOCUMENTARIES", "MUSIC", "GENERAL"]
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
    logger.debug("Richiesta manifest servita")
    return response

@app.route('/', methods=['GET'])
def root():
    """Reindirizzamento alla pagina di installazione"""
    logger.debug("Reindirizzamento alla pagina di installazione")
    return redirect('/install')

# Endpoint per il catalogo (formato standard Stremio)
@app.route('/catalog/<type>/<id>.json', methods=['GET'])
def catalog(type, id):
    logger.info(f"Richiesta catalogo: {type}/{id}")
    
    # Controlliamo che il tipo e id corrispondano a quelli supportati
    if type != "tv" or id != "vavoo_italy":
        logger.warning(f"Tipo o ID non supportati: {type}/{id}")
        return jsonify({"metas": []})
        
    search = request.args.get('search', '')
    skip = int(request.args.get('skip', 0))
    genre = request.args.get('genre', '')
    
    return get_catalog_response(type, id, search, skip, genre)

# Endpoint per il catalogo con parametro search/genre/skip nel percorso (formato Stremio)
@app.route('/catalog/<type>/<id>/<extra>.json', methods=['GET'])
def catalog_with_extra(type, id, extra):
    logger.info(f"Richiesta catalogo con extra: {type}/{id}/{extra}")
    
    # Controlliamo che il tipo e id corrispondano a quelli supportati
    if type != "tv" or id != "vavoo_italy":
        logger.warning(f"Tipo o ID non supportati: {type}/{id}")
        return jsonify({"metas": []})
    
    search = ""
    skip = 0
    genre = ""
    
    # Parsing dei parametri extra
    if extra.startswith("search="):
        search = extra.split("=", 1)[1]
    elif extra.startswith("skip="):
        try:
            skip = int(extra.split("=", 1)[1])
        except ValueError:
            skip = 0
    elif extra.startswith("genre="):
        genre = extra.split("=", 1)[1]
    
    return get_catalog_response(type, id, search, skip, genre)

def get_catalog_response(type, id, search, skip, genre=""):
    channels = load_italian_channels()
    
    # Filtra per la ricerca se specificata
    if search:
        logger.info(f"Ricerca canali con query: {search}")
        search_norm = normalize_text(search)
        channels = [ch for ch in channels if search_norm in normalize_text(ch["name"])]
        logger.info(f"Trovati {len(channels)} canali per la ricerca '{search}'")
    
    # Filtra per genere se specificato (usando le linee guida ufficiali di Stremio)
    if genre:
        logger.info(f"Filtro canali per genere: {genre}")
        # Assegniamo il genere a ciascun canale e filtriamo
        filtered_channels = []
        for channel in channels:
            channel_genre = get_channel_genre(channel["name"])
            if channel_genre == genre:
                filtered_channels.append(channel)
        
        channels = filtered_channels
        logger.info(f"Trovati {len(channels)} canali per il genere '{genre}'")
    
    # Ordina i canali per nome
    channels = sorted(channels, key=lambda ch: ch["name"])
    
    # Applica paginazione
    total_channels = len(channels)
    channels = channels[skip:skip+100]
    
    logger.info(f"Restituisco {len(channels)} canali (skip={skip}, totale={total_channels})")
    
    metas = []
    for channel in channels:
        # Trova il genere e il logo appropriato per il canale
        channel_genre = get_channel_genre(channel["name"])
        logo_url = find_logo_for_channel(channel["name"])
        
        metas.append({
            "id": f"{ID_PREFIX}{channel['id']}",  # Aggiungi il prefisso all'ID
            "type": "tv",
            "name": channel["name"],
            "genres": [channel_genre],
            "poster": logo_url,  # Usa il logo del canale come poster
            "posterShape": "square",
            "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}",
            "logo": logo_url  # Usa lo stesso logo come icona del canale
        })
    
    return jsonify({"metas": metas})

# Endpoint per i meta (formato standard Stremio)
@app.route('/meta/<type>/<id>.json', methods=['GET'])
def meta(type, id):
    logger.info(f"Richiesta meta: {type}/{id}")
    
    # Controlliamo che il tipo sia supportato e che l'ID abbia il nostro prefisso
    if type != "tv" or not id.startswith(ID_PREFIX):
        logger.warning(f"Tipo o prefisso ID non supportati: {type}/{id}")
        return jsonify({"meta": None})
    
    # Rimuoviamo il prefisso per ottenere l'ID originale
    channel_id = id[len(ID_PREFIX):]
    
    channels = load_italian_channels()
    channel = next((ch for ch in channels if str(ch["id"]) == channel_id), None)
    
    if not channel:
        logger.warning(f"Canale con ID {channel_id} non trovato")
        return jsonify({"meta": None})
    
    genre = get_channel_genre(channel["name"])
    logo_url = find_logo_for_channel(channel["name"])
    
    meta_obj = {
        "id": f"{ID_PREFIX}{channel['id']}",  # Manteniamo il prefisso nell'ID
        "type": "tv",
        "name": channel["name"],
        "genres": [genre],
        "poster": logo_url,
        "posterShape": "square",
        "background": f"https://via.placeholder.com/1280x720/000080/FFFFFF?text={quote(channel['name'])}",
        "logo": logo_url,
        "description": f"Canale TV italiano: {channel['name']}",
        "releaseInfo": "24/7 Live"
    }
    
    logger.info(f"Meta servito per canale: {channel['name']}")
    return jsonify({"meta": meta_obj})

# Endpoint per lo stream (formato standard Stremio)
@app.route('/stream/<type>/<id>.json', methods=['GET'])
def stream(type, id):
    logger.info(f"Richiesta stream: {type}/{id}")
    
    # Controlliamo che il tipo sia supportato e che l'ID abbia il nostro prefisso
    if type != "tv" or not id.startswith(ID_PREFIX):
        logger.warning(f"Tipo o prefisso ID non supportati: {type}/{id}")
        return jsonify({"streams": []})
    
    # Rimuoviamo il prefisso per ottenere l'ID originale
    channel_id = id[len(ID_PREFIX):]
    
    # Costruisci l'URL dello stream
    stream_url = VAVOO_STREAM_BASE_URL.format(id=channel_id)
    
    # Costruisci l'URL del proxy con HTTPS
    base_url = get_base_url()
            
    headers_str = "&".join([f"header_{quote(k)}={quote(v)}" for k, v in DEFAULT_HEADERS.items()])
    proxied_url = f"{base_url}/proxy/m3u?url={quote(stream_url)}&{headers_str}"
    
    channels = load_italian_channels()
    channel = next((ch for ch in channels if str(ch["id"]) == channel_id), None)
    channel_name = channel["name"] if channel else "Unknown"
    
    logger.info(f"Stream servito per canale: {channel_name}")
    
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
        logger.error("Parametro 'url' mancante nella richiesta proxy m3u")
        return "Errore: Parametro 'url' mancante", 400

    # Headers di default per evitare blocchi del server
    headers = {**DEFAULT_HEADERS, **{
        unquote(key[7:]).replace("_", "-"): unquote(value).strip()
        for key, value in request.args.items()
        if key.lower().startswith("header_")
    }}

    try:
        logger.info(f"Proxy m3u: richiesta a {m3u_url}")
        response = requests.get(m3u_url, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()
        final_url = response.url  
        m3u_content = response.text

        file_type = detect_m3u_type(m3u_content)
        logger.debug(f"Tipo file m3u rilevato: {file_type}")

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
        logger.info(f"Proxy m3u: elaborazione completata ({len(modified_m3u8)} linee)")
        return Response(modified_m3u8_content, content_type="application/vnd.apple.mpegurl")

    except requests.Timeout:
        logger.error(f"Timeout durante il download del file M3U/M3U8: {m3u_url}")
        return f"Errore: Timeout durante il download del file M3U/M3U8", 504
    except requests.RequestException as e:
        logger.error(f"Errore durante il download del file M3U/M3U8: {str(e)}")
        return f"Errore durante il download del file M3U/M3U8: {str(e)}", 500

# Endpoint per il proxy ts
@app.route('/proxy/ts')
def proxy_ts():
    """ Proxy per segmenti .TS con headers personalizzati e gestione dei redirect """
    ts_url = request.args.get('url', '').strip()
    if not ts_url:
        logger.error("Parametro 'url' mancante nella richiesta proxy ts")
        return "Errore: Parametro 'url' mancante", 400

    # Otteniamo gli headers dalla query string
    headers = {**DEFAULT_HEADERS, **{
        unquote(key[7:]).replace("_", "-"): unquote(value).strip()
        for key, value in request.args.items()
        if key.lower().startswith("header_")
    }}

    try:
        response = requests.get(ts_url, headers=headers, stream=True, allow_redirects=True, timeout=15)
        response.raise_for_status()
        return Response(response.iter_content(chunk_size=1024), content_type="video/mp2t")
    
    except requests.Timeout:
        logger.error(f"Timeout durante il download del segmento TS: {ts_url}")
        return f"Errore: Timeout durante il download del segmento TS", 504
    except requests.RequestException as e:
        logger.error(f"Errore durante il download del segmento TS: {str(e)}")
        return f"Errore durante il download del segmento TS: {str(e)}", 500

# Istruzioni per l'installazione dell'addon su Stremio
@app.route('/install')
def install_instructions():
    base_url = get_base_url()
    stremio_url = f"stremio://{request.host}/manifest.json"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Installazione Vavoo.to Italia Addon</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
            .button {{ display: inline-block; background-color: #2196F3; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin-bottom: 20px; }}
            .code {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-wrap: break-word; word-wrap: break-word; }}
            .info {{ margin-top: 30px; padding: 15px; background-color: #e0f7fa; border-radius: 4px; }}
            @media (max-width: 600px) {{
                body {{ padding: 10px; }}
            }}
        </style>
    </head>
    <body>
        <h1>Vavoo.to Italia Addon per Stremio</h1>
        <p>Questo addon ti permette di guardare i canali TV italiani disponibili su Vavoo.to direttamente all'interno di Stremio.</p>
        
        <h2>Installazione</h2>
        <p>Per installare l'addon, clicca sul pulsante qui sotto:</p>
        <a class="button" href="{stremio_url}">Installa su Stremio</a>
        
        <h3>Installazione manuale</h3>
        <p>In alternativa, puoi aggiungere manualmente questo URL in Stremio:</p>
        <div class="code">{base_url}/manifest.json</div>
        
        <div class="info">
            <h3>Informazioni</h3>
            <p>Versione: {ADDON_VERSION}</p>
            <p>L'addon proxy i flussi direttamente da Vavoo.to.</p>
            <p>Per qualsiasi problema, contatta l'amministratore dell'addon.</p>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/status.json')
def status():
    """Endpoint per verificare lo stato dell'addon"""
    channels = load_italian_channels()
    logos = load_logos()
    
    return jsonify({
        "status": "online",
        "channels_count": len(channels),
        "logos_count": len(logos),
        "channels_cache_timestamp": cache_timestamp,
        "channels_cache_age_seconds": time.time() - cache_timestamp if cache_timestamp > 0 else 0,
        "logos_cache_timestamp": CACHE_LOGOS_TIMESTAMP,
        "logos_cache_age_seconds": time.time() - CACHE_LOGOS_TIMESTAMP if CACHE_LOGOS_TIMESTAMP > 0 else 0,
        "version": ADDON_VERSION
    })

@app.route('/<path:invalid_path>')
def catch_all(invalid_path):
    """Gestisci percorsi non validi reindirizzando alla pagina di installazione"""
    logger.warning(f"Percorso non valido richiesto: {invalid_path}")
    return redirect('/install')

if __name__ == '__main__':
    # Configurazione per l'ambiente di produzione
    port = int(os.environ.get('PORT', 10000))
    
    # Se è definita la variabile di ambiente DEBUG, abilita il debug mode
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Avvio server su porta {port}, debug_mode={debug_mode}")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
