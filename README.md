# LLM Wycena – ostatnie zmiany

Poniższe punkty opisują wprowadzone zmiany w logice wyceny i przepływie danych:

## Rozdzielenie źródeł danych
- Dane „twarde” zbierane bezpośrednio od klienta nadal są pobierane z maili.
- Dane wrażliwe lub obarczone ryzykiem subiektywności są pozyskiwane z OSINT (sieć).

## Nowy silnik wyceny (SOC 2)
- Wycena jest liczona per obszar Trust Services Criteria:
  - Security (baseline, zawsze obowiązkowe)
  - Availability, Confidentiality, Processing Integrity, Privacy (opcjonalne)
- Każdy obszar ma stałe widełki cenowe, a całość jest skalowana współczynnikiem **X = F(p)**.

## Współczynnik X = F(p)
Wartość X zależy od atrybutów firmy:
- geografia (kraj centrali),
- język komunikacji,
- różnica strefy czasowej względem CET,
- kultura biznesowa,
- skala biznesu (szacowane przychody).

## OSINT – rozszerzony zakres
Z OSINT zbieramy teraz:
- branżę,
- kraj,
- szacowane przychody,
- język,
- strefę czasową (offset UTC),
- kulturę biznesową.

## Wynik wyceny
Wycena zwraca:
- rozbicie na obszary (widełki i szacunek),
- łączny zakres minimalny/maksymalny,
- szacunek końcowy i uzasadnienie współczynnika X.
