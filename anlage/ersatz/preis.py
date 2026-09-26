"""Preis-Sensor eines Ersatz-Paars (Palladium → Platin): reine Rechenwege ohne Netz.

Zwei Arten von Signal, beide am Original:
- Sprung: Der Kurs steigt binnen `anstieg_tage` Handelstagen um mindestens `anstieg_ab`.
- Verhältnis: Das Original wird teurer als der Ersatz (Verhältnis der Kurse steigt über `verhaeltnis_ab`).
Nach einem Signal zählt das nächste erst nach `pause_tage` Handelstagen, damit eine lange Welle
nicht mehrfach in den Rückblick eingeht.
"""
from __future__ import annotations


def gemeinsam(original: list[dict], ersatz: list[dict]) -> list[tuple[str, float, float]]:
    """Handelstage, an denen beide Kurse vorliegen: (Datum, Original, Ersatz)."""
    e = {x["datum"]: x["schluss"] for x in ersatz if x.get("schluss")}
    return [(x["datum"], x["schluss"], e[x["datum"]]) for x in original if x.get("schluss") and x["datum"] in e]


def signale(original: list[dict], ersatz: list[dict], s: dict) -> list[dict]:
    reihe = gemeinsam(original, ersatz)
    n, liste, letzter = s["anstieg_tage"], [], None
    for i, (d, o, e) in enumerate(reihe):
        if letzter is not None and i - letzter < s["pause_tage"]:
            continue
        treffer = None
        if i >= n and reihe[i - n][1]:
            r = o / reihe[i - n][1] - 1
            if r >= s["anstieg_ab"]:
                treffer = {"datum": d, "art": "Sprung", "wert": round(r, 4)}
        if treffer is None and i > 0:
            vorher = reihe[i - 1][1] / reihe[i - 1][2]
            jetzt = o / e
            if vorher < s["verhaeltnis_ab"] <= jetzt:
                treffer = {"datum": d, "art": "Verhältnis", "wert": round(jetzt, 3)}
        if treffer:
            treffer["verhaeltnis"] = round(o / e, 3)
            liste.append(treffer)
            letzter = i
    return liste


def lage(original: list[dict], ersatz: list[dict], s: dict) -> dict:
    """Heutiger Stand: Veränderung des Originals über das Anstiegsfenster und das Verhältnis."""
    reihe = gemeinsam(original, ersatz)
    if not reihe:
        return {"datum": None, "anstieg": None, "verhaeltnis": None}
    d, o, e = reihe[-1]
    n = s["anstieg_tage"]
    anstieg = round(o / reihe[-1 - n][1] - 1, 4) if len(reihe) > n and reihe[-1 - n][1] else None
    return {"datum": d, "anstieg": anstieg, "verhaeltnis": round(o / e, 3)}
