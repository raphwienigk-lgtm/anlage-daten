"""El Niño: oberster Schalter der Kaskade.

Liest die ONI-Reihe, erkennt die jüngste El-Niño-Episode und ihren Höhepunkt.

Regeln:
- Eine Episode sind mindestens fünf Jahreszeiten in Folge ab +0,5 (Regel der NOAA).
  Eine einzelne Jahreszeit knapp darunter unterbricht sie nicht.
- Eine Folge, die gerade läuft, zählt schon vorher als „beginnende“ Episode. Wirkt aber
  noch eine vollständige frühere Episode nach, bleibt diese maßgeblich; die neue
  Erwärmung wird nur gemeldet.
- Der Höhepunkt gilt erst als bestätigt, wenn danach mindestens zwei Jahreszeiten
  niedriger lagen. Vorher läuft die Uhr für das Zeitfenster noch nicht.
- Eine Episode, deren Höhepunkt länger als T + 6 Monate zurückliegt, zählt nicht mehr.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..rechnen.kennzahlen import begrenze, monate_zwischen


def staerke_text(wert: float) -> str:
    betrag = abs(wert)
    if betrag < 0.5:
        return "neutral"
    if betrag < 1.0:
        return "schwach"
    if betrag < 1.5:
        return "mäßig"
    if betrag < 2.0:
        return "stark"
    return "sehr stark"


def _kurz(eintrag: dict) -> dict:
    return {"jahreszeit": eintrag["jahreszeit"], "jahr": eintrag["jahr"],
            "monat": eintrag["monat"], "wert": eintrag["wert"]}


def _monat_verschieben(tag: date, monate: int) -> date:
    index = tag.year * 12 + tag.month - 1 + monate
    return date(index // 12, index % 12 + 1, 1)


def erster_tag(eintrag: dict) -> date:
    """Erster Tag einer Dreimonats-Jahreszeit. JAS 2026 beginnt am 1. Juli 2026,
    DJF 2027 am 1. Dezember 2026."""
    return _monat_verschieben(date(eintrag["jahr"], eintrag["monat"], 1), -1)


def letzter_tag(eintrag: dict) -> date:
    """Letzter Tag einer Dreimonats-Jahreszeit. JAS 2026 endet am 30. September 2026."""
    letzter_monat = _monat_verschieben(erster_tag(eintrag), 2)
    return date(letzter_monat.year, letzter_monat.month,
                calendar.monthrange(letzter_monat.year, letzter_monat.month)[1])


def _folgen(reihe: list[dict], ab: float) -> list[list[int]]:
    """Folgen von Jahreszeiten ab der Schwelle als [Beginn, Ende] (Indizes).
    Liegt genau eine Jahreszeit dazwischen unter der Schwelle, werden zwei Folgen verbunden."""
    folgen = []
    k = 0
    while k < len(reihe):
        if reihe[k]["wert"] >= ab:
            beginn = k
            while k + 1 < len(reihe) and reihe[k + 1]["wert"] >= ab:
                k += 1
            if folgen and beginn - folgen[-1][1] == 2:
                folgen[-1][1] = k
            else:
                folgen.append([beginn, k])
        k += 1
    return folgen


def _episode(reihe: list[dict], beginn: int, ende: int, schwellen: dict, heute: date) -> dict:
    hoch = max(range(beginn, ende + 1), key=lambda k: (reihe[k]["wert"], k))   # bei Gleichstand der spätere
    laeuft = ende == len(reihe) - 1
    bestaetigt = len(reihe) - 1 - hoch >= schwellen.get("hoehepunkt_bestaetigt_nach", 2)
    hoehepunkt = _kurz(reihe[hoch])
    monate_seit = monate_zwischen(hoehepunkt["jahr"], hoehepunkt["monat"], heute)
    laenge = ende - beginn + 1
    return {
        "beginn": _kurz(reihe[beginn]),
        "ab": erster_tag(reihe[beginn]).isoformat(),
        "ende": None if laeuft else _kurz(reihe[ende]),
        "bis": None if laeuft else letzter_tag(reihe[ende]).isoformat(),
        "laeuft": laeuft,
        "beginnend": laeuft and laenge < schwellen.get("mindest_jahreszeiten", 5),
        "laenge_jahreszeiten": laenge,
        "hoehepunkt": hoehepunkt,
        "hoehepunkt_bestaetigt": bestaetigt,
        "monate_seit_hoehepunkt": monate_seit if bestaetigt else None,
    }


def _wirkt_noch(episode: dict, vorlauf_monate: int) -> bool:
    if episode["laeuft"] or not episode["hoehepunkt_bestaetigt"]:
        return True
    return episode["monate_seit_hoehepunkt"] <= vorlauf_monate + 6


def lage(reihe: list[dict], schwellen: dict, heute: date, vorlauf_monate: int = 12) -> dict:
    ab = schwellen["el_nino_ab"]
    mindest = schwellen.get("mindest_jahreszeiten", 5)
    letzte = reihe[-1]
    if letzte["wert"] >= ab:
        phase = "El Niño"
    elif letzte["wert"] <= schwellen["la_nina_bis"]:
        phase = "La Niña"
    else:
        phase = "neutral"

    ergebnis = {
        "aktuell": _kurz(letzte),
        "phase": phase,
        "staerke_text": staerke_text(letzte["wert"]),
        "episode": None,
        "neue_erwaermung": None,
        "staerke": 0.0,
        "stufe1": phase == "El Niño",
    }

    letzter_index = len(reihe) - 1
    kandidaten = [(b, e) for b, e in _folgen(reihe, ab) if e - b + 1 >= mindest or e == letzter_index]
    if not kandidaten:
        return ergebnis
    episode = _episode(reihe, *kandidaten[-1], schwellen, heute)
    if episode["beginnend"] and len(kandidaten) > 1:
        frueher = _episode(reihe, *kandidaten[-2], schwellen, heute)
        if _wirkt_noch(frueher, vorlauf_monate):
            ergebnis["neue_erwaermung"] = {"beginn": episode["beginn"],
                                           "laenge_jahreszeiten": episode["laenge_jahreszeiten"]}
            episode = frueher
    if not _wirkt_noch(episode, vorlauf_monate):
        return ergebnis
    ergebnis["episode"] = episode
    ergebnis["staerke"] = round(begrenze(episode["hoehepunkt"]["wert"] / schwellen["staerke_voll_bei"]), 3)
    return ergebnis


def episoden(reihe: list[dict], schwellen: dict) -> list[dict]:
    """Alle El-Niño-Episoden der Reihe mit mindestens fünf Jahreszeiten (für den Rückblick).
    Eine Folge am Ende der Reihe zählt mit, sobald sie lang genug ist, und hat dann kein Ende."""
    ab = schwellen["el_nino_ab"]
    mindest = schwellen.get("mindest_jahreszeiten", 5)
    liste = []
    for beginn, ende in _folgen(reihe, ab):
        if ende - beginn + 1 < mindest:
            continue
        hoch = max(range(beginn, ende + 1), key=lambda k: (reihe[k]["wert"], k))
        laeuft = ende == len(reihe) - 1
        liste.append({"beginn": _kurz(reihe[beginn]), "ende": None if laeuft else _kurz(reihe[ende]),
                      "hoehepunkt": _kurz(reihe[hoch]), "laenge_jahreszeiten": ende - beginn + 1,
                      "laeuft": laeuft})
    return liste


def episode_beginn(enso_lage: dict | None) -> date | None:
    """Ab diesem Tag zählen Wind, Dipol und Regenzeugen zur laufenden Episode."""
    if not enso_lage or not enso_lage.get("episode"):
        return None
    return date.fromisoformat(enso_lage["episode"]["ab"])


def zaehlt_bis(enso_lage: dict | None, nachlauf_tage: int = 120) -> date | None:
    """Bis zu diesem Tag zählen Dürre, Nässe und Dipol noch zur Episode.
    None, solange die Episode läuft."""
    if not enso_lage or not enso_lage.get("episode") or not enso_lage["episode"]["bis"]:
        return None
    return date.fromisoformat(enso_lage["episode"]["bis"]) + timedelta(days=nachlauf_tage)


def episode_jahre(enso_lage: dict | None, heute: date) -> list[int]:
    """Jahre, deren Mai und Juni zur Episode gehören (für Stufe 2, die Ostwinde).

    Der 1. Mai des Jahres muss zwischen sechs Monaten vor Beginn der Episode und dem
    Höhepunkt liegen (bei laufender Episode ohne bestätigten Höhepunkt: bis heute).
    Beispiel: Beginn MJJ 2026, Höhepunkt NDJ 2026 → nur 2026.
    """
    beginn = episode_beginn(enso_lage)
    if beginn is None:
        return []
    episode = enso_lage["episode"]
    if episode["laeuft"] and not episode["hoehepunkt_bestaetigt"]:
        obergrenze = heute
    else:
        obergrenze = erster_tag(episode["hoehepunkt"])
    untergrenze = _monat_verschieben(beginn, -6)
    return [j for j in range(untergrenze.year, obergrenze.year + 1)
            if untergrenze <= date(j, 5, 1) <= min(obergrenze, heute)]


def zeitfenster(enso_lage: dict | None, vorlauf_monate: int) -> dict:
    """Zeitfenster = 1 − t/T, t = Monate seit dem El-Niño-Höhepunkt, T = typische Vorlaufzeit.

    Solange der Höhepunkt nicht bestätigt ist, ist das Fenster voll offen (1,0).
    """
    if not enso_lage or not enso_lage.get("episode"):
        return {"wert": None, "status": "kein Ereignis", "t_monate": None, "T_monate": vorlauf_monate}
    episode = enso_lage["episode"]
    if not episode["hoehepunkt_bestaetigt"]:
        return {"wert": 1.0, "status": "Höhepunkt noch nicht erreicht, Uhr läuft noch nicht",
                "t_monate": 0, "T_monate": vorlauf_monate}
    t = max(0, episode["monate_seit_hoehepunkt"])
    wert = round(begrenze(1 - t / vorlauf_monate), 3)
    status = "abgelaufen" if wert == 0 else "läuft"
    return {"wert": wert, "status": status, "t_monate": t, "T_monate": vorlauf_monate}
