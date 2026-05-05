import pandas as pd
import os

def extract_xlsx_to_txt(input_file, output_file):
    print(f"⏳ Rozpoczynam ekstrakcję z pliku: {input_file}...")

    if not os.path.exists(input_file):
        print(f"❌ Błąd: Nie znaleziono pliku '{input_file}'. Upewnij się, że jest w tym samym folderze co skrypt.")
        return

    try:
        # Wczytujemy plik Excela
        xls = pd.ExcelFile(input_file)

        # Otwieramy plik tekstowy do zapisu
        with open(output_file, mode='w', encoding='utf-8') as outfile:
            # Przechodzimy przez wszystkie arkusze w pliku
            for sheet_name in xls.sheet_names:
                outfile.write(f"=========================================\n")
                outfile.write(f"=== ARKUSZ: {sheet_name} ===\n")
                outfile.write(f"=========================================\n")

                # Wczytujemy dane z konkretnego arkusza
                df = pd.read_excel(xls, sheet_name=sheet_name)

                # Zamieniamy tabelę na czytelny tekst i zapisujemy
                # to_string() formatuje to w ładne kolumny
                outfile.write(df.to_string(index=False))
                outfile.write("\n\n")

        print(f"✅ Sukces! Dane ze wszystkich arkuszy zostały skopiowane do: {output_file}")

    except Exception as e:
        print(f"❌ Wystąpił błąd podczas przetwarzania: {e}")

if __name__ == "__main__":
    # Dokładna nazwa pliku Excel, który wgrałeś
    plik_wejsciowy = "SOC wycena AS.xlsx"

    # Plik docelowy
    plik_wyjsciowy = "dane_do_czatu.txt"

    extract_xlsx_to_txt(plik_wejsciowy, plik_wyjsciowy)