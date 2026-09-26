"""Regenzeugen der Kreuzbestätigung.

Ostzeuge: Regen der letzten 90 Tage auf Sumatra und Borneo im Vergleich zum Normalen.
Westzeuge: Regen der kurzen Regenzeit in Ostafrika (Oktober bis Dezember), seit Beginn
der Saison, im Vergleich zum Normalen. Außerhalb der Saison schweigt der Westzeuge.

Zwei Blickwinkel:
- „aktuell“: wie es heute aussieht (für den Überblick).
- „in der Episode“: ob der Zeuge seit Beginn der laufenden El-Niño-Episode
  angeschlagen hat. Das zählt für die Ampel. Der Preisgipfel beim Palmöl kommt erst
  Monate nach der Dürre; wenn die Ampel auf Rot springen darf, regnet es auf Sumatra
  oft längst wieder normal. Ohne diesen Blick zurück wäre Rot kaum erreichbar.

„Normal“ ist der mittlere Tagesregen je Kalendertag im Zeitraum 1991 bis 2020
(Datei daten/klima/regen.json, einmalig erzeugt mit `python -m anlage.klimatologie`).
Verglichen werden nur Tage, für die ein Messwert vorliegt.
"""
from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, timedelta


def klimatologie(tageswerte: dict[str, float | None]) -> dict[str, float]:
    """Mittlerer Wert je Kalendertag ('MM-TT') über alle Jahre."""
    sammel = defaultdict(list)
    for datum, wert in tageswerte.items():
        if wert is not None:
            sammel[datum[5:10]].append(wert)
    return {tag: round(sum(v) / len(v), 3) for tag, v in sorted(sammel.items())}


def anteil(ist: dict[str, float | None], normal: dict[str, float], start: date, ende: date) -> dict:
    summe_ist = summe_normal = 0.0
    tage = 0
    tag = start
    while tag <= ende:
        schluessel = tag.isoformat()
        wert = ist.get(schluessel)
        if wert is not None and schluessel[5:] in normal:
            summe_ist += wert
            summe_normal += normal[schluessel[5:]]
            tage += 1
        tag += timedelta(days=1)
    return {
        "tage": tage,
        "summe_mm": round(summe_ist, 1),
        "normal_mm": round(summe_normal, 1),
        "anteil": round(summe_ist / summe_normal, 3) if summe_normal > 0 else None,
    }


def letzter_messtag(ist: dict[str, float | None], bis: date | None = None) -> date | None:
    grenze = bis.isoformat() if bis else "9999"
    tage = [d for d, w in ist.items() if w is not None and d <= grenze]
    return date.fromisoformat(max(tage)) if tage else None


def _mittel(werte: list[float | None]) -> float | None:
    werte = [w for w in werte if w is not None]
    return round(sum(werte) / len(werte), 3) if werte else None


def _nur_mit_normal(daten: dict, normal: dict) -> tuple[dict, list[str]]:
    mit = {n: ist for n, ist in daten.items() if n in normal}
    return mit, [n for n in daten if n not in normal]


# ------------------------------------------------------------------ Ostzeuge
def ostzeuge(daten: dict[str, dict], normal: dict[str, dict], schwellen: dict) -> dict:
    """Aktueller Stand: Regen der letzten 90 Tage bis zum letzten Messtag je Punkt.

    daten: {Punktname: Tageswerte}; normal: {Punktname: Klimatologie}.
    """
    if not normal:
        return {"status": "Klimatologie fehlt", "an": None, "anteil": None, "punkte": {}, "fehlend": list(daten)}
    tage = schwellen["tage"]
    mit, fehlend = _nur_mit_normal(daten, normal)
    punkte = {}
    for name, ist in mit.items():
        ende = letzter_messtag(ist)
        if ende is None:
            fehlend.append(name)
            continue
        punkte[name] = {**anteil(ist, normal[name], ende - timedelta(days=tage - 1), ende),
                        "bis": ende.isoformat()}
    region = _mittel([p["anteil"] for p in punkte.values()])
    if region is None:
        return {"status": "keine Daten", "an": None, "anteil": None, "punkte": punkte, "fehlend": fehlend}
    return {
        "status": "gemessen",
        "an": region <= schwellen["trocken_bis_anteil"],
        "anteil": region,
        "zeitraum_tage": tage,
        "bis": min(p["bis"] for p in punkte.values()),
        "punkte": punkte,
        "fehlend": fehlend,
    }


def ostzeuge_verlauf(daten: dict[str, dict], normal: dict[str, dict], schwellen: dict, ab: date,
                     bis: date | None = None) -> dict:
    """War es seit `ab` (und bis `bis`) an irgendeinem Tag 90 Tage lang zu trocken?

    Für jeden Tag wird das 90-Tage-Fenster davor bewertet. Gezählt werden nur Fenster,
    die mindestens zur Hälfte in der Episode liegen, also frühestens 45 Tage nach `ab`
    enden. Eine Dürre vor der Episode zählt so nicht mit. Ein Punkt zählt an einem Tag
    nur, wenn mindestens 80 % der Tage im Fenster gemessen sind; die Region zählt nur,
    wenn mindestens die Hälfte der Punkte vorliegt.
    """
    if not normal:
        return {"status": "Klimatologie fehlt", "an": None}
    tage = schwellen["tage"]
    grenze = schwellen["trocken_bis_anteil"]
    mit, _ = _nur_mit_normal(daten, normal)
    enden = [e for e in (letzter_messtag(ist) for ist in mit.values()) if e]
    if not enden:
        return {"status": "keine Daten", "an": None}
    ende = min(max(enden), bis) if bis else max(enden)
    erstes_ende = ab + timedelta(days=tage // 2)
    if ende < erstes_ende:
        return {"status": "seit Beginn der Episode noch zu kurz gemessen", "an": None}

    start = ab - timedelta(days=tage - 1)
    anzahl = (ende - start).days + 1
    schluessel = [(start + timedelta(days=k)).isoformat() for k in range(anzahl)]
    summen = []
    for name, ist in mit.items():
        s_ist, s_norm, s_n = [0.0], [0.0], [0]
        for s in schluessel:
            wert, norm = ist.get(s), normal[name].get(s[5:])
            gueltig = wert is not None and norm is not None
            s_ist.append(s_ist[-1] + (wert if gueltig else 0.0))
            s_norm.append(s_norm[-1] + (norm if gueltig else 0.0))
            s_n.append(s_n[-1] + (1 if gueltig else 0))
        summen.append((s_ist, s_norm, s_n))

    mindest_punkte = max(1, math.ceil(len(summen) / 2))
    erster = tiefster = tiefster_tag = letzter_tag = None
    trockene_tage = 0
    for k in range((erstes_ende - start).days, anzahl):
        a, b = k - tage + 1, k + 1
        anteile = []
        for s_ist, s_norm, s_n in summen:
            if s_n[b] - s_n[a] >= 0.8 * tage and s_norm[b] - s_norm[a] > 0:
                anteile.append((s_ist[b] - s_ist[a]) / (s_norm[b] - s_norm[a]))
        if len(anteile) < mindest_punkte:
            continue
        region = sum(anteile) / len(anteile)
        letzter_tag = schluessel[k]
        if tiefster is None or region < tiefster:
            tiefster, tiefster_tag = region, schluessel[k]
        if region <= grenze:
            trockene_tage += 1
            erster = erster or schluessel[k]
    if tiefster is None:
        return {"status": "zu wenige Messwerte", "an": None}
    return {
        "status": "gemessen",
        "an": trockene_tage > 0,
        "ab": erstes_ende.isoformat(),
        "bis": letzter_tag,
        "erster_trockener_tag": erster,
        "trockene_tage": trockene_tage,
        "tiefster_anteil": round(tiefster, 3),
        "tiefster_tag": tiefster_tag,
    }


# ------------------------------------------------------------------ Westzeuge
def _saisongrenzen(jahr: int, monate: list[int]) -> tuple[date, date]:
    beginn = date(jahr, monate[0], 1)
    schluss = date(jahr, monate[-1], calendar.monthrange(jahr, monate[-1])[1])
    return beginn, schluss


def saison(daten: dict[str, dict], normal: dict[str, dict], schwellen: dict,
           jahr: int, stichtag: date) -> dict:
    """Kurze Regenzeit des Jahres `jahr`, bewertet bis `stichtag`."""
    monate = schwellen["monate"]
    beginn, schluss = _saisongrenzen(jahr, monate)
    grund = {"jahr": jahr, "von": beginn.isoformat(), "bis_ende": schluss.isoformat()}
    if stichtag < beginn:
        return {**grund, "status": "noch nicht begonnen", "an": None, "anteil": None}
    if not normal:
        return {**grund, "status": "Klimatologie fehlt", "an": None, "anteil": None}
    mit, fehlend = _nur_mit_normal(daten, normal)
    punkte = {}
    for name, ist in mit.items():
        ende = letzter_messtag(ist, min(stichtag, schluss))
        if ende is None or ende < beginn:
            fehlend.append(name)
            continue
        punkte[name] = {**anteil(ist, normal[name], beginn, ende), "bis": ende.isoformat()}
    region = _mittel([p["anteil"] for p in punkte.values()])
    tage = min((p["tage"] for p in punkte.values()), default=0)
    if region is None:
        return {**grund, "status": "keine Daten", "an": None, "anteil": None, "punkte": punkte, "fehlend": fehlend}
    if tage < schwellen["mindest_tage"]:
        return {**grund, "status": "Saison zu jung", "an": None, "anteil": region, "tage": tage,
                "punkte": punkte, "fehlend": fehlend}
    abgeschlossen = min(p["bis"] for p in punkte.values()) >= schluss.isoformat()
    return {
        **grund,
        "status": "abgeschlossen" if abgeschlossen else "läuft",
        "an": region >= schwellen["nass_ab_anteil"],
        "anteil": region,
        "tage": tage,
        "punkte": punkte,
        "fehlend": fehlend,
    }


def westzeuge(daten: dict[str, dict], normal: dict[str, dict], schwellen: dict, heute: date) -> dict:
    """Aktueller Stand. Außerhalb der Saison: Hinweis auf die nächste und die letzte Saison."""
    monate = schwellen["monate"]
    if heute.month in monate:
        return {**saison(daten, normal, schwellen, heute.year, heute), "in_saison": True}
    naechstes = heute.year if heute.month < monate[0] else heute.year + 1
    letztes = naechstes - 1
    return {
        "status": "außer Saison",
        "an": None,
        "anteil": None,
        "in_saison": False,
        "saison_ab": date(naechstes, monate[0], 1).isoformat(),
        "letzte_saison": saison(daten, normal, schwellen, letztes, heute),
    }


def westzeuge_verlauf(daten: dict[str, dict], normal: dict[str, dict], schwellen: dict,
                      ab: date, heute: date, bis: date | None = None) -> dict:
    """Hat eine Regenzeit der Episode zu viel Regen gebracht?

    Gezählt werden die Regenzeiten, die frühestens 45 Tage nach `ab` enden und bis heute
    (höchstens bis `bis`) begonnen haben. Eine laufende Regenzeit zählt mit ihrem
    heutigen Stand und kann noch kippen.
    """
    monate = schwellen["monate"]
    grenze = min(heute, bis) if bis else heute
    saisons = []
    for jahr in range(ab.year - 1, heute.year + 1):
        beginn, schluss = _saisongrenzen(jahr, monate)
        if schluss >= ab + timedelta(days=45) and beginn <= grenze:
            saisons.append(saison(daten, normal, schwellen, jahr, heute))
    if not saisons:
        return {"status": "seit Beginn der Episode noch keine Regenzeit", "an": None, "saisons": []}
    bewertet = [s for s in saisons if s["an"] is not None]
    kurz = [{k: s.get(k) for k in ("jahr", "status", "an", "anteil", "tage")} for s in saisons]
    if not bewertet:
        return {"status": saisons[-1]["status"], "an": None, "saisons": kurz}
    return {"status": "gemessen", "an": any(s["an"] for s in bewertet), "saisons": kurz}


# ------------------------------------------------------------------ beide
def zeugen(ost_daten: dict, west_daten: dict, normal: dict, schwellen: dict,
           heute: date, ab: date | None, bis: date | None = None) -> dict:
    """Beide Zeugen, jeweils aktuell und (bei laufender Episode) seit Beginn der Episode.

    normal: Inhalt von regen.json, {'punkte': {Punktname: Klimatologie}}.
    """
    punkte_normal = (normal or {}).get("punkte", {})
    s_ost, s_west = schwellen["ost"], schwellen["west"]
    return {
        "ost": {
            "aktuell": ostzeuge(ost_daten, punkte_normal, s_ost),
            "episode": ostzeuge_verlauf(ost_daten, punkte_normal, s_ost, ab, bis) if ab else None,
        },
        "west": {
            "aktuell": westzeuge(west_daten, punkte_normal, s_west, heute),
            "episode": westzeuge_verlauf(west_daten, punkte_normal, s_west, ab, heute, bis) if ab else None,
        },
    }
