# silnik_wyceny.py

class AuditsolutionsPricingV2:
    def __init__(self):
        # Widełki wg wytycznych (USD/EUR)
        # JEŚLI WYCENY SĄ ZA WYSOKIE/NISKIE, ZMIEŃ TYLKO TE WARTOŚCI:
        self.ranges = {
            "security": {"min": 12000, "max": 25000},
            "availability": {"min": 2000, "max": 5000},
            "confidentiality": {"min": 3000, "max": 6000},
            "processing_integrity": {"min": 5000, "max": 10000},
            "privacy": {"min": 8000, "max": 15000}
        }
        self.base_rate_eur_per_md = 800.0

    def calculate(self, data) -> dict:
        # 1. USTALANIE WIDEŁEK BAZOWYCH
        total_min = self.ranges["security"]["min"]
        total_max = self.ranges["security"]["max"]

        dodatkowe_domeny = getattr(data, 'dodatkowe_domeny', []) or []
        for domena in dodatkowe_domeny:
            d_lower = domena.lower()
            if "availability" in d_lower or "dostępność" in d_lower:
                total_min += self.ranges["availability"]["min"]
                total_max += self.ranges["availability"]["max"]
            elif "confidentiality" in d_lower or "poufność" in d_lower:
                total_min += self.ranges["confidentiality"]["min"]
                total_max += self.ranges["confidentiality"]["max"]
            elif "processing integrity" in d_lower:
                total_min += self.ranges["processing_integrity"]["min"]
                total_max += self.ranges["processing_integrity"]["max"]
            elif "privacy" in d_lower or "prywatność" in d_lower:
                total_min += self.ranges["privacy"]["min"]
                total_max += self.ranges["privacy"]["max"]

        # 2. OBLICZANIE SUWAKA 'X'
        x_score = 0.30

        liczba_pracownikow = getattr(data, 'liczba_pracownikow', 0) or 0
        if liczba_pracownikow > 500: x_score += 0.40
        elif liczba_pracownikow > 200: x_score += 0.20
        elif liczba_pracownikow > 50: x_score += 0.10

        infrastruktura = getattr(data, 'infrastruktura', '') or ''
        if "on-premise" in infrastruktura.lower() or "hybryd" in infrastruktura.lower():
            x_score += 0.15

        if getattr(data, 'posiada_iso27001', False): x_score -= 0.25
        if getattr(data, 'korzysta_z_narzedzi_compliance', False): x_score -= 0.20

        dojrzalosc = getattr(data, 'ocena_dojrzalosci_it', 5)
        if dojrzalosc >= 8: x_score -= 0.15
        elif dojrzalosc <= 3: x_score += 0.15

        kraj = getattr(data, 'kraj_centrali', 'Polska').lower()
        if any(k in kraj for k in ["usa", "united states", "canada", "mexico"]): x_score += 0.10

        kultura_hierarchiczna = ["spain", "italy", "portugal", "greece", "india", "uae", "mexico", "brazil"]
        if any(k in kraj for k in kultura_hierarchiczna): x_score += 0.15

        przychody = getattr(data, 'szacowane_przychody_mln_usd', 0) or 0
        if przychody > 50: x_score += 0.20

        x_score = max(0.0, min(1.0, x_score))

        # 3. WYLICZENIE FINALNEJ CENY
        final_fee = total_min + (x_score * (total_max - total_min))
        cost_type1 = round(final_fee, 2)
        cost_type2 = round(final_fee * 1.5, 2)

        is_high_risk = (liczba_pracownikow > 200) and not getattr(data, 'posiada_iso27001', False)
        model = "Time & Material + wstępne Gap Analysis" if is_high_risk else "Fixed Price"

        return {
            "rekomendowany_model": model,
            "wspolczynnik_x": round(x_score, 2),
            "widellki_min": total_min,
            "widellki_max": total_max,
            "wycena_type1_eur": cost_type1,
            "wycena_type2_eur": cost_type2
        }