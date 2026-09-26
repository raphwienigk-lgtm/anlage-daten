"""Spätfrost-Sensor: reine Rechenwege ohne Netz.

Eine Frostnacht zählt, wenn an mindestens `mindest` Anbauorten das Tagesminimum auf oder
unter der Schwelle liegt. Stark ist eine Nacht, wenn das auch für die tiefere Schwelle gilt.
"""
from __future__ import annotations

from datetime import date, timedelta


def saison_grenzen(jahr: int, saison: dict) -> tuple[date, date]:
    von = date.fromisoformat(f"{jahr}-{saison['von']}")
    bis = date.fromisoformat(f"{jahr}-{saison['bis']}")
    return von, bis


def phase(heute: date, s: dict) -> str:
    """„Vorwarnung“, „Saison“ oder „außer Saison“."""
    von, bis = saison_grenzen(heute.year, s["saison"])
    if von <= heute <= bis:
        return "Saison"
    if von - timedelta(days=s.get("vorwarnung_tage", 0)) <= heute < von:
        return "Vorwarnung"
    return "außer Saison"


def naechte(werte: dict[str, dict[str, float | None]], schwelle: float, stark: float, mindest: int,
            von: date | None = None, bis: date | None = None) -> list[dict]:
    """Frostnächte aus {Standort: {Datum: Tagesminimum}}; je Nacht die betroffenen Orte."""
    alle_tage = sorted({d for tage in werte.values() for d in tage})
    ergebnis = []
    for d in alle_tage:
        if (von and d < von.isoformat()) or (bis and d > bis.isoformat()):
            continue
        messwerte = {k: tage.get(d) for k, tage in werte.items() if tage.get(d) is not None}
        kalt = sorted(k for k, w in messwerte.items() if w <= schwelle)
        if len(kalt) < mindest:
            continue
        sehr_kalt = [k for k, w in messwerte.items() if w <= stark]
        ergebnis.append({"datum": d, "orte": kalt, "tiefste": round(min(messwerte[k] for k in kalt), 1),
                         "stark": len(sehr_kalt) >= mindest})
    return ergebnis


def tiefste(werte: dict[str, dict[str, float | None]], von: date, bis: date) -> float | None:
    alle = [w for tage in werte.values() for d, w in tage.items()
            if w is not None and von.isoformat() <= d <= bis.isoformat()]
    return round(min(alle), 1) if alle else None


def saison_urteil(werte: dict, jahr: int, s: dict) -> dict:
    """Eine Saison zusammengefasst: Zahl der Frostnächte, erste Nacht, tiefster Wert, Urteil."""
    von, bis = saison_grenzen(jahr, s["saison"])
    liste = naechte(werte, s["schwelle_c"], s["stark_c"], s["mindest_standorte"], von, bis)
    if any(n["stark"] for n in liste):
        urteil = "starker Spätfrost"
    elif liste:
        urteil = "Spätfrost"
    else:
        urteil = "ruhig"
    return {"jahr": jahr, "urteil": urteil, "frostnaechte": len(liste),
            "erste": liste[0]["datum"] if liste else None,
            "erste_starke": next((n["datum"] for n in liste if n["stark"]), None),
            "tiefste": tiefste(werte, von, bis)}


def abgleich(saisons: list[dict], bekannte: list[int]) -> dict:
    """Welche belegten Frostjahre der Sensor erkennt, und wie viele andere Jahre er meldet."""
    erkannt = [s["jahr"] for s in saisons if s["urteil"] != "ruhig"]
    geprueft = [j for j in bekannte if any(s["jahr"] == j for s in saisons)]
    return {"erkannte_jahre": erkannt,
            "bekannte_getroffen": [j for j in geprueft if j in erkannt],
            "bekannte_verfehlt": [j for j in geprueft if j not in erkannt],
            "weitere": [j for j in erkannt if j not in bekannte],
            "jahre_geprueft": len(saisons)}
