"""El-Niño-Index (ONI) und Dipol-Index (DMI) als Textdateien."""
from __future__ import annotations

import re

from .. import netz
from ..netz import AbrufFehler

JAHRESZEITEN = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ",
                "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
_ZAHL = re.compile(r"[-+]?\d+(?:\.\d+)?")


def lies_oni(text: str) -> list[dict]:
    """ONI-Datei der NOAA: Zeilen wie 'JAS 2026  28.10   1.23'.

    Die Mitte der Jahreszeit bestimmt den Monat: DJF = Januar, NDJ = Dezember.
    """
    reihe = []
    for zeile in text.splitlines():
        teile = zeile.split()
        if len(teile) != 4 or teile[0] not in JAHRESZEITEN or not teile[1].isdigit():
            continue
        try:
            anomalie = float(teile[3])
        except ValueError:
            continue
        if abs(anomalie) >= 99:
            continue
        reihe.append({
            "jahreszeit": teile[0],
            "jahr": int(teile[1]),
            "monat": JAHRESZEITEN.index(teile[0]) + 1,
            "wert": anomalie,
        })
    if not reihe:
        raise AbrufFehler("ONI-Datei enthielt keine lesbaren Zeilen")
    return reihe


def lies_monatsreihe(text: str) -> list[dict]:
    """Jahr plus zwölf Monatswerte je Zeile (Format von NOAA PSL und JMA).

    Fehlwerte wie -9999 oder 99.9 werden übersprungen.
    """
    reihe = []
    for zeile in text.splitlines():
        zahlen = _ZAHL.findall(zeile)
        if len(zahlen) != 13:
            continue
        jahr_text = zahlen[0]
        if not re.fullmatch(r"\d{4}", jahr_text):
            continue
        jahr = int(jahr_text)
        if not 1850 <= jahr <= 2100:
            continue
        for monat, wert_text in enumerate(zahlen[1:], start=1):
            wert = float(wert_text)
            if abs(wert) >= 99:
                continue
            reihe.append({"jahr": jahr, "monat": monat, "wert": wert})
    if not reihe:
        raise AbrufFehler("Monatsreihe enthielt keine lesbaren Werte")
    reihe.sort(key=lambda e: (e["jahr"], e["monat"]))
    return reihe


def hole_oni(url: str) -> list[dict]:
    return lies_oni(netz.hole_text(url))


def hole_dmi(quellen: list[dict]) -> tuple[list[dict], str]:
    """Probiert die DMI-Quellen der Reihe nach. Gibt Reihe und Quellenname zurück."""
    fehler = []
    for quelle in quellen:
        try:
            return lies_monatsreihe(netz.hole_text(quelle["url"])), quelle["name"]
        except AbrufFehler as f:
            fehler.append(f"{quelle['name']}: {f}")
    raise AbrufFehler("Keine DMI-Quelle lesbar. " + " | ".join(fehler))
