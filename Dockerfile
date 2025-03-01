FROM python:3.9-slim

WORKDIR /app

# Installa le dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice dell'applicazione
COPY app.py .

# Espone la porta usata da Render (10000)
ENV PORT=10000
EXPOSE 10000

# Avvia l'applicazione
CMD ["python", "app.py"]
