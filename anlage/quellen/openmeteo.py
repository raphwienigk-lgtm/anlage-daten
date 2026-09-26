"""Open-Meteo-Archiv (ERA5-Reanalyse): Tagesregen und stündlicher Wind je Punkt.

Achtung Tageslimit: Abrufe über mehr als zwei Wochen zählen bei Open-Meteo als
mehrere Abrufe. Lange Zeiträume holt deshalb nur die Klimatologie, einmalig.
"""
from __future__ import annotations

import math
import re
import time
from datetime import date

from .. import netz
from ..netz import AbrufFehler


class KeineWerte(AbrufFehler):
    """Die Quelle antwortet, hat für den Zeitraum aber noch keine Messwerte (ERA5 liegt Tage zurück)."""


def gewicht(tage: int, variablen: int = 1) -> float:
    """So viele Abrufe rechnet Open-Meteo an: je angefangene zwei Wochen und je zehn Variablen."""
    return max(1.0, tage / 14) * max(1.0, variablen / 10)


def drossel(abrufe: float, pro_minute: float) -> None:
    """Wartet so lange, dass im Mittel höchstens pro_minute gewichtete Abrufe anfallen."""
    if pro_minute > 0:
        time.sleep(60.0 * abrufe / pro_minute)


_SPANNE = re.compile(r"out of allowed range from \d{4}-\d{2}-\d{2} to (\d{4}-\d{2}-\d{2})")


def _hole(url: str, parameter: dict) -> dict:
    """Abruf mit einer Korrektur: Liegt das Enddatum hinter den verfügbaren Daten,
    nennt Open-Meteo die erlaubte Spanne. Dann einmal mit diesem Enddatum neu versuchen."""
    try:
        return netz.hole_json(url, parameter)
    except AbrufFehler as fehler:
        treffer = _SPANNE.search(str(fehler))
        if not treffer or treffer.group(1) >= parameter["end_date"] or treffer.group(1) < parameter["start_date"]:
            raise
        return netz.hole_json(url, {**parameter, "end_date": treffer.group(1)})


def _pruefe(antwort: dict, punkt: dict) -> dict:
    if not isinstance(antwort, dict):
        raise AbrufFehler(f"Unerwartete Antwort für {punkt['name']}")
    if antwort.get("error"):
        raise AbrufFehler(f"Open-Meteo meldet für {punkt['name']}: {antwort.get('reason')}")
    return antwort


def _parameter(punkt: dict, start: date, ende: date, modell: str | None, **weitere) -> dict:
    parameter = {"latitude": punkt["lat"], "longitude": punkt["lon"],
                 "start_date": start.isoformat(), "end_date": ende.isoformat(),
                 "timezone": "UTC", **weitere}
    if modell:
        parameter["models"] = modell
    return parameter


def hole_tage(url: str, punkt: dict, start: date, ende: date,
              variable: str = "precipitation_sum", modell: str | None = None) -> dict[str, float | None]:
    """Tageswerte als {'JJJJ-MM-TT': Wert}. Fehlende Tage haben None."""
    antwort = _pruefe(_hole(url, _parameter(punkt, start, ende, modell, daily=variable)), punkt)
    taeglich = antwort.get("daily") or {}
    tage = taeglich.get("time") or []
    werte = taeglich.get(variable) or []
    if not tage or len(tage) != len(werte):
        raise AbrufFehler(f"Keine Tageswerte für {punkt['name']}")
    return dict(zip(tage, werte))


def zonalwind(geschwindigkeit: float, richtung_grad: float) -> float:
    """Ost-West-Anteil des Windes in m/s. Negativ heißt: Wind aus Osten.

    Die Richtung ist meteorologisch angegeben, also woher der Wind kommt.
    """
    return -geschwindigkeit * math.sin(math.radians(richtung_grad))


def hole_mittleren_zonalwind(url: str, punkt: dict, start: date, ende: date,
                             modell: str | None = None) -> tuple[float, int]:
    """Mittlerer Ost-West-Wind in 10 m Höhe über den Zeitraum, in m/s, und die Zahl der Stunden."""
    antwort = _pruefe(_hole(url, _parameter(
        punkt, start, ende, modell,
        hourly="wind_speed_10m,wind_direction_10m", wind_speed_unit="ms")), punkt)
    stuendlich = antwort.get("hourly") or {}
    tempo = stuendlich.get("wind_speed_10m") or []
    richtung = stuendlich.get("wind_direction_10m") or []
    if not tempo or len(tempo) != len(richtung):
        raise AbrufFehler(f"Unerwartete Windantwort für {punkt['name']}")
    paare = [(v, r) for v, r in zip(tempo, richtung) if v is not None and r is not None]
    if not paare:
        raise KeineWerte(f"Noch keine Windwerte für {punkt['name']}")
    return sum(zonalwind(v, r) for v, r in paare) / len(paare), len(paare)
