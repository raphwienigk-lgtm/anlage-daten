"""Grundlegende Kennzahlen."""
from __future__ import annotations

from datetime import date
from statistics import mean, pstdev


def begrenze(x: float, unten: float = 0.0, oben: float = 1.0) -> float:
    return max(unten, min(oben, x))


def zwert(werte: list[float], fenster: int) -> float | None:
    """Z = (P − MA) / SD über die letzten `fenster` Werte, P ist der letzte Wert.

    Stark positiv heißt: Preis heiß gelaufen. None, wenn zu wenige Werte vorliegen.
    """
    if fenster < 2 or len(werte) < fenster:
        return None
    teil = werte[-fenster:]
    streuung = pstdev(teil)
    if streuung == 0:
        return None
    return (teil[-1] - mean(teil)) / streuung


def veraenderung(reihe: list[dict], tage: int = 91, feld: str = "schluss") -> float | None:
    """Relative Veränderung des letzten Werts gegenüber dem Wert vor `tage` Kalendertagen."""
    if len(reihe) < 2:
        return None
    letzter = reihe[-1]
    stichtag = date.fromisoformat(letzter["datum"]).toordinal() - tage
    frueher = None
    for eintrag in reihe:
        if date.fromisoformat(eintrag["datum"]).toordinal() <= stichtag:
            frueher = eintrag
        else:
            break
    if frueher is None or not frueher[feld]:
        return None
    return letzter[feld] / frueher[feld] - 1


def volumen_trend(reihe: list[dict], tage: int = 20) -> float | None:
    """Durchschnittsvolumen der letzten `tage` Handelstage geteilt durch die `tage` davor.

    Unter 1 heißt: Das Volumen lässt nach. Grundlage für das Ausstiegssignal
    „Bewegung wird müde“.
    """
    volumen = [e["volumen"] for e in reihe if e.get("volumen")]
    if len(volumen) < 2 * tage:
        return None
    jetzt, vorher = mean(volumen[-tage:]), mean(volumen[-2 * tage:-tage])
    return jetzt / vorher if vorher else None


def monate_zwischen(jahr: int, monat: int, heute: date) -> int:
    return (heute.year - jahr) * 12 + (heute.month - monat)
