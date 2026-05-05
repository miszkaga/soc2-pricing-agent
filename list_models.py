import os
import google.generativeai as genai
from dotenv import load_dotenv

# Wczytujemy klucz z pliku .env
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("Błąd: Nie znaleziono klucza GOOGLE_API_KEY w pliku .env")
    exit()

# Konfigurujemy autoryzację
genai.configure(api_key=api_key)

print("Dostępne modele wspierające generowanie tekstu (generateContent):\n")

# Pobieramy listę modeli
for m in genai.list_models():
    # Filtrujemy tylko te, które potrafią generować tekst (omijamy np. starsze modele tylko do embedingów)
    if 'generateContent' in m.supported_generation_methods:
        print(f"- Nazwa: {m.name}")
        print(f"  Opis: {m.description}")
        print("-" * 50)