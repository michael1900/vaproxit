import os

# Configurazione Gunicorn per Render
workers = int(os.environ.get('GUNICORN_WORKERS', 2))
threads = int(os.environ.get('GUNICORN_THREADS', 4))
bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"
worker_class = 'gthread'
timeout = 120  # Lungo timeout per le richieste proxy
