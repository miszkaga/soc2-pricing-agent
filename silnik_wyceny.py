from typing import Optional


class AuditsolutionsPricingV2:
    AREA_RANGES_USD = {
        "security": {"label": "Security (Baseline)", "min": 22000, "max": 60000},
        "availability": {"label": "Availability", "min": 3000, "max": 9000},
        "confidentiality": {"label": "Confidentiality", "min": 5000, "max": 12000},
        "processing_integrity": {"label": "Processing Integrity", "min": 8000, "max": 18000},
        "privacy": {"label": "Privacy", "min": 15000, "max": 35000},
    }
    AREA_ALIASES = {
        "security": ["security", "bezpieczenstwo", "bezpieczeństwo", "baseline"],
        "availability": ["availability", "dostepnosc", "dostępność"],
        "confidentiality": ["confidentiality", "poufnosc", "poufność"],
        "processing_integrity": ["processing integrity", "integrity", "integralnosc", "integralność", "jakosc", "jakość"],
        "privacy": ["privacy", "prywatnosc", "prywatność"],
    }
    HIGH_COST_COUNTRY_KEYWORDS = ["usa", "united states", "uk", "united kingdom", "switzerland", "germany", "netherlands", "sweden", "norway", "denmark"]
    LOW_COST_COUNTRY_KEYWORDS = ["poland", "polska", "czech", "slovakia", "romania", "bulgaria", "hungary"]

    def calculate(self, data, research: Optional[dict] = None) -> dict:
        research = research or {}
        selected_areas = self._select_areas(data)
        factor, factor_notes = self._pricing_factor(research)

        breakdown = []
        total_min = 0
        total_max = 0
        total_estimate = 0

        for area_key in selected_areas:
            area = self.AREA_RANGES_USD[area_key]
            estimate = self._estimate_from_range(area["min"], area["max"], factor)
            breakdown.append({
                "key": area_key,
                "label": area["label"],
                "min_usd": area["min"],
                "max_usd": area["max"],
                "estimate_usd": estimate
            })
            total_min += area["min"]
            total_max += area["max"]
            total_estimate += estimate

        return {
            "x_factor": round(factor, 2),
            "x_factor_notes": factor_notes,
            "areas": breakdown,
            "total_min_usd": total_min,
            "total_max_usd": total_max,
            "total_estimate_usd": total_estimate
        }

    def _select_areas(self, data) -> list:
        selected = ["security"]
        raw_areas = data.dodatkowe_domeny or []
        if isinstance(raw_areas, str):
            raw_areas = [raw_areas]
        for area in raw_areas:
            normalized = self._normalize_area_name(area)
            if normalized and normalized not in selected and normalized != "security":
                selected.append(normalized)
        return selected

    def _normalize_area_name(self, area_name: str) -> Optional[str]:
        if not area_name:
            return None
        lowered = area_name.strip().lower()
        for key, aliases in self.AREA_ALIASES.items():
            if lowered == key or any(alias in lowered for alias in aliases):
                return key
        return None

    def _pricing_factor(self, research: dict) -> tuple:
        score = 0.5
        notes = []

        country = (research.get("kraj_centrali") or "").lower()
        if any(keyword in country for keyword in self.HIGH_COST_COUNTRY_KEYWORDS):
            score += 0.12
            notes.append("geografia: rynek wysokokosztowy")
        elif any(keyword in country for keyword in self.LOW_COST_COUNTRY_KEYWORDS):
            score -= 0.08
            notes.append("geografia: rynek niższokosztowy")

        language = (research.get("jezyk_glowny") or "").lower()
        if language and language not in ["polski", "polish", "english", "angielski"]:
            score += 0.05
            notes.append("język: dodatkowa warstwa komunikacji")

        tz_offset = self._safe_int(research.get("strefa_czasowa_utc_offset"))
        if tz_offset is not None:
            diff = abs(tz_offset - 1)
            if diff >= 6:
                score += 0.07
                notes.append("strefa czasowa: duża różnica względem CET")
            elif diff >= 3:
                score += 0.04
                notes.append("strefa czasowa: umiarkowana różnica względem CET")

        culture = (research.get("kultura_biznesowa") or "").lower()
        if any(keyword in culture for keyword in ["korpor", "enterprise", "formal", "regulated", "korporacyjna"]):
            score += 0.05
            notes.append("kultura: korporacyjna/formalna")
        elif any(keyword in culture for keyword in ["startup", "nieformal", "zwin", "agile"]):
            score -= 0.03
            notes.append("kultura: startupowa/nieformalna")

        revenue = self._safe_float(research.get("szacowane_przychody_mln_usd"))
        if revenue is not None:
            if revenue > 100:
                score += 0.05
                notes.append("skala: przychody > 100 mln USD")
            elif revenue > 50:
                score += 0.03
                notes.append("skala: przychody > 50 mln USD")
            elif revenue < 10:
                score -= 0.03
                notes.append("skala: przychody < 10 mln USD")

        score = min(max(score, 0.2), 0.85)
        return score, notes

    @staticmethod
    def _estimate_from_range(min_value: float, max_value: float, factor: float) -> int:
        estimate = min_value + factor * (max_value - min_value)
        return int(round(estimate, -2))

    @staticmethod
    def _safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
