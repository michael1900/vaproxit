FROM python:3.9-slim

WORKDIR /app

# Copia prima solo i file necessari per le dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia esplicitamente il file JSON
COPY canali_con_loghi_finale.json .

# Poi copia il resto del codice
COPY . .

# Comando per avviare l'applicazione
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
