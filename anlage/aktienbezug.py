"""Welche Aktie folgt dem Rohstoffpreis am engsten? Nur Messwerte, keine Empfehlung.

Für jeden Rohstoff und jede Aktie unter `instrumente` im Formular:

- Monatsmittel der Schlusskurse (Yahoo, so weit zurück wie möglich) gegen die
  Monatspreise des Rohstoffs (Weltbank-Geschichte, verlängert mit FRED)
- Korrelation der Veränderungen über einen Monat und über zwölf Monate
- Mitnahme: um wie viel Prozent die Aktie im Mittel stieg, wenn der Rohstoff
  in zwölf Monaten um zehn Prozent stieg (Steigung der Ausgleichsgeraden)
- Jahre mit starkem Anstieg: Veränderung der Aktie in den Zwölf-Monats-Spannen, in
  denen der Rohstoff um mindestens 20 Prozent stieg, gegen alle Spannen
- Handel: mittlerer Tagesumsatz der letzten zwölf Monate in Landeswährung

Die Kurse sind in Landeswährung (SGD), der Rohstoffpreis in US-Dollar; das
verwischt die Zahlen etwas, ändert aber die Reihenfolge selten.

Schreibt daten/aktienbezug.json, abgabe/aktienbezug-teil-N.md, abgabe/status-aktienbezug.md.
Aufruf: python -m anlage.aktienbezug [--heute JJJJ-MM-TT]
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from statistics import mean, median

from . import __version__, konfig, speicher
from .bilanz import monat_text, monats_index
from .kipppunkte import steigung
from .quellen import kurse

HINWEIS = "Denkhilfe, keine Anlageberatung. Messwerte ohne Empfehlung."
STARK_AB = 0.20            # Zwölf-Monats-Anstieg des Rohstoffs, der als stark gilt
MINDEST_MONATE = 36


def korrelation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def monatsmittel(tage: list[dict]) -> dict[int, float]:
    """Tageskurse {'datum', 'schluss'} → {Monatsindex: Mittel}; Monate mit weniger als zehn Kursen fallen weg."""
    gruppen: dict[int, list[float]] = {}
    for e in tage:
        gruppen.setdefault(monats_index(e["datum"][:7]), []).append(e["schluss"])
    return {i: mean(w) for i, w in gruppen.items() if len(w) >= 10}


def rohstoff_monate(kennung: str, k: dict) -> dict[int, float]:
    """Weltbank-Geschichte, für spätere Monate verlängert mit FRED (gleiche Einheit US-Dollar je Tonne)."""
    preise: dict[int, float] = {}
    geschichte = speicher.lies_json(konfig.GESCHICHTE / "preise.json", {}) or {}
    for e in (geschichte.get("reihen") or {}).get(kennung) or []:
        preise[monats_index(e["datum"][:7])] = e["wert"]
    serie = (k["rohstoffe"][kennung].get("preis") or {}).get("serie")
    for e in speicher.lies_json(konfig.PREISE / f"fred_{serie}.json", []) or []:
        preise.setdefault(monats_index(e["datum"][:7]), e["wert"])
    return preise


def _veraenderung(reihe: dict[int, float], i: int, h: int) -> float | None:
    if i in reihe and i + h in reihe and reihe[i]:
        return reihe[i + h] / reihe[i] - 1
    return None


def vergleiche(aktie: dict[int, float], rohstoff: dict[int, float]) -> dict | None:
    gemeinsam = sorted(set(aktie) & set(rohstoff))
    if len(gemeinsam) < MINDEST_MONATE:
        return None
    paare_1 = [(v, w) for i in gemeinsam
               if (v := _veraenderung(rohstoff, i, 1)) is not None and (w := _veraenderung(aktie, i, 1)) is not None]
    paare_12 = [(v, w) for i in gemeinsam
                if (v := _veraenderung(rohstoff, i, 12)) is not None and (w := _veraenderung(aktie, i, 12)) is not None]
    if len(paare_12) < 12:
        return None
    stark = [w for v, w in paare_12 if v >= STARK_AB]
    b = steigung([v for v, _ in paare_12], [w for _, w in paare_12])
    return {
        "von": monat_text(gemeinsam[0]), "bis": monat_text(gemeinsam[-1]), "monate": len(gemeinsam),
        "korrelation_1": _r(korrelation(*zip(*paare_1)) if len(paare_1) >= 3 else None),
        "korrelation_12": _r(korrelation(*zip(*paare_12))),
        "mitnahme": _r(b),
        "stark_spannen": len(stark),
        "stark_mittel": _r(mean(stark)) if stark else None,
        "alle_mittel": _r(mean(w for _, w in paare_12)),
    }


def _r(x, stellen=3):
    return None if x is None else round(x, stellen)


def handel(tage: list[dict], heute: date) -> float | None:
    """Mittlerer Tagesumsatz (Kurs mal Stückzahl) der letzten zwölf Monate, als Median."""
    grenze = date(heute.year - 1, heute.month, 1).isoformat()
    umsaetze = [e["schluss"] * e["volumen"] for e in tage if e["datum"] >= grenze and e.get("volumen")]
    return round(median(umsaetze)) if umsaetze else None


def rechne(k: dict, heute: date, zeitpunkt, holen=kurse.hole_yahoo) -> dict:
    ergebnis = {}
    for kennung, r in k["rohstoffe"].items():
        aktien = [i for i in r.get("instrumente") or [] if i.get("art") == "Aktie"]
        if not aktien:
            continue
        rohstoff = rohstoff_monate(kennung, k)
        liste = []
        for a in aktien:
            eintrag = {"ticker": a["ticker"], "name": a.get("name", a["ticker"]), "hinweis": a.get("hinweis")}
            try:
                tage = holen(a["ticker"], "max")
                v = vergleiche(monatsmittel(tage), rohstoff)
                eintrag.update({"status": "ok" if v else "zu kurz", **(v or {}), "handel": handel(tage, heute),
                                "erster_tag": tage[0]["datum"] if tage else None})
            except Exception as fehler:  # eine Aktie darf die anderen nicht mitreißen
                eintrag.update({"status": "Fehler", "meldung": f"{type(fehler).__name__}: {fehler}"[:300]})
            liste.append(eintrag)
        reihenfolge = sorted((e for e in liste if e.get("korrelation_12") is not None),
                             key=lambda e: -e["korrelation_12"])
        ergebnis[kennung] = {"name": r.get("name", kennung), "rohstoff_bis": monat_text(max(rohstoff)) if rohstoff else None,
                             "aktien": liste, "reihenfolge": [e["ticker"] for e in reihenfolge]}
    return {"stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "version": __version__,
            "hinweis": HINWEIS, "stark_ab": STARK_AB, "rohstoffe": ergebnis}


def main(argv: list[str] | None = None) -> int:
    from .ausgabe import aktienbezug_text

    teiler = argparse.ArgumentParser(description="Wie eng folgen die Aktien dem Rohstoffpreis?")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    args = teiler.parse_args(argv)
    k = konfig.konfiguration()
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    ergebnis = rechne(k, zeitpunkt.date(), zeitpunkt)
    speicher.schreibe_json(konfig.DATEN / "aktienbezug.json", ergebnis)
    aktienbezug_text.schreibe(ergebnis, konfig.ABGABE)
    print(aktienbezug_text.zusammenfassung(ergebnis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
