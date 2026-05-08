class AuditsolutionsPricingV2:
    def __init__(self):
        self.base_rate_eur_per_md = 800.0  # Wewnętrzna stawka za 1 MD audytora

    def calculate(self, data) -> dict:
        # ---------------------------------------------------------
        # KROK 1: SZACOWANIE PRACOCHŁONNOŚCI (Man-Days dla Type 1)
        # ---------------------------------------------------------
        base_md = 15.0  # Baza: 15 dni roboczych dla prostej firmy (Tylko Security)

        # Wielkość firmy (Skala)
        if data.liczba_pracownikow:
            if data.liczba_pracownikow > 500:
                base_md += 20.0
            elif data.liczba_pracownikow > 200:
                base_md += 10.0
            elif data.liczba_pracownikow > 50:
                base_md += 5.0

        # Złożoność infrastruktury i lokalizacji
        if data.infrastruktura and "on-premise" in data.infrastruktura.lower():
            base_md += 5.0
        if data.liczba_lokalizacji:
            base_md += (data.liczba_lokalizacji * 2.0)
        if data.dodatkowe_domeny:
            base_md += (len(data.dodatkowe_domeny) * 4.0)

        # Trudność branży (Regulacje)
        branza = (data.branza or "").lower()
        if any(x in branza for x in ["fintech", "medtech", "banking", "healthcare"]):
            base_md *= 1.25  # +25% czasu na cięższe regulacje

        # Zniżki za dojrzałość procesową (Optymalizacja pracy)
        if data.posiada_iso27001:
            base_md *= 0.85  # -15% czasu
        if data.korzysta_z_narzedzi_compliance:
            base_md *= 0.80  # -20% czasu, bo Vanta/Drata robi za nas część dowodów

        # ---------------------------------------------------------
        # KROK 2: WYCENA TYPE 2 (Opcjonalnie)
        # ---------------------------------------------------------
        # Zakładamy, że Type 2 to czas poświęcony na Type 1 + 50% czasu na testowanie w okresie
        md_type1 = base_md
        md_type2 = base_md * 1.5

        # ---------------------------------------------------------
        # KROK 3: NAKŁADANIE MARŻY (Pricing Power)
        # ---------------------------------------------------------
        margin = 0.20  # Bazowa marża 20%

        # Narzut rynkowy
        kraj = (data.kraj_centrali or "Polska").lower()
        if any(x in kraj for x in ["usa", "uk", "szwajcaria", "niemcy"]):
            margin += 0.20  # Klienci z zachodu płacą wyższą stawkę

        # Narzut za wielkość biznesu
        if data.szacowane_przychody_mln_usd and data.szacowane_przychody_mln_usd > 50:
            margin += 0.15

        # ---------------------------------------------------------
        # KROK 4: ZARZĄDZANIE RYZYKIEM (Fixed vs T&M)
        # ---------------------------------------------------------
        # Jeśli firma jest duża, nie ma ISO, nie ma Vanty i trudna branża -> nie ryzykujemy Fixed Price
        is_high_risk = (data.liczba_pracownikow and data.liczba_pracownikow > 200) and not data.posiada_iso27001
        model = "Time & Material + wstępne Gap Analysis" if is_high_risk else "Fixed Price"

        # ---------------------------------------------------------
        # KROK 5: OSTATECZNE KALKULACJE
        # ---------------------------------------------------------
        cost_type1 = round(md_type1 * self.base_rate_eur_per_md * (1 + margin), 2)
        cost_type2 = round(md_type2 * self.base_rate_eur_per_md * (1 + margin), 2)

        return {
            "rekomendowany_model": model,
            "szacowane_md_type1": round(md_type1, 1),
            "marza_procent": round(margin * 100, 0),
            "wycena_type1_eur": cost_type1,
            "wycena_type2_eur": cost_type2
        }