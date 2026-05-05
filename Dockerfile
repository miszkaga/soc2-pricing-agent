# Używamy lekkiej, oficjalnej wersji Pythona
FROM python:3.11-slim

# Ustawiamy katalog roboczy
WORKDIR /app

# Kopiujemy pliki z wymaganymi bibliotekami (najpierw requirements, dla optymalizacji)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiujemy resztę Twojego kodu i tokeny
COPY . .

# Uruchamiamy skrypt
CMD ["python", "main.py"]