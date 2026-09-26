"""Abrufe für den Metall-Agenten: Bundesregister, Erdbeben, Regen.

Jede Funktion nimmt die Adresse aus konfig/quellen.yaml und gibt einfache Listen und
Wörterbücher zurück. Fehler kommen als AbrufFehler, der Lauf geht dann weiter.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

from .. import netz
from ..netz import AbrufFehler

FELDER = ["title", "publication_date", "agencies", "html_url", "type", "document_number", "abstract"]


# ------------------------------------------------------------------ Bundesregister
def lies_bundesregister(antwort: dict) -> list[dict]:
    if not isinstance(antwort, dict):
        raise AbrufFehler("Bundesregister: unerwartete Antwort")
    if antwort.get("errors"):
        raise AbrufFehler(f"Bundesregister meldet: {antwort['errors']}")
    dokumente = []
    for e in antwort.get("results") or []:
        behoerden = [a for a in e.get("agencies") or [] if isinstance(a, dict)]
        dokumente.append({
            "nummer": e.get("document_number"),
            "titel": " ".join((e.get("title") or "").split()),
            "datum": e.get("publication_date"),
            "art": e.get("type"),
            "behoerden": [a.get("slug") for a in behoerden if a.get("slug")],
            "behoerden_namen": [a.get("name") or a.get("raw_name") for a in behoerden if a.get("name") or a.get("raw_name")],
            "url": e.get("html_url"),
            "zusammenfassung": " ".join((e.get("abstract") or "").split())[:600],
        })
    return [d for d in dokumente if d["nummer"]]


def hole_bundesregister(url: str, begriff: str, ab: date, behoerden: list[str] | None = None) -> list[dict]:
    """Einträge ab `ab`, deren Volltext den Begriff enthält. Mehrwortbegriffe als Wortgruppe.
    Mit `behoerden` nur Einträge dieser Stellen (Kürzel wie im Bundesregister)."""
    suche = f'"{begriff}"' if " " in begriff else begriff
    params = {"conditions[term]": suche, "conditions[publication_date][gte]": ab.isoformat(),
              "per_page": 100, "order": "newest", "fields[]": FELDER}
    if behoerden:
        params["conditions[agencies][]"] = list(behoerden)
    return lies_bundesregister(netz.hole_json(url, params))


# ------------------------------------------------------------------ Erdbeben
def lies_erdbeben(antwort: dict) -> list[dict]:
    if not isinstance(antwort, dict) or "features" not in antwort:
        raise AbrufFehler("USGS: unerwartete Antwort")
    beben = []
    for f in antwort["features"]:
        p = f.get("properties") or {}
        koord = (f.get("geometry") or {}).get("coordinates") or []
        if p.get("mag") is None or len(koord) < 2 or p.get("time") is None:
            continue
        zeit = datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc)
        beben.append({"kennung": f.get("id"), "staerke": round(float(p["mag"]), 1), "ort": p.get("place"),
                      "datum": zeit.date().isoformat(), "zeit": zeit.isoformat(timespec="minutes"),
                      "lat": float(koord[1]), "lon": float(koord[0]),
                      "tiefe_km": float(koord[2]) if len(koord) > 2 and koord[2] is not None else None,
                      "url": p.get("url")})
    return beben


def hole_erdbeben(url: str, ab: date, mindest: float, box: tuple[float, float, float, float]) -> list[dict]:
    """Beben ab `ab` und ab Stärke `mindest` im Rechteck (Süd, Nord, West, Ost)."""
    sued, nord, west, ost = box
    params = {"format": "geojson", "starttime": ab.isoformat(), "minmagnitude": mindest,
              "minlatitude": sued, "maxlatitude": nord, "minlongitude": west, "maxlongitude": ost,
              "orderby": "time"}
    return lies_erdbeben(netz.hole_json(url, params))


def abstand_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Großkreis-Abstand in Kilometern."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def suchrechteck(standorte: list[dict], rand_grad: float = 4.0) -> tuple[float, float, float, float]:
    lat = [s["lat"] for s in standorte]
    lon = [s["lon"] for s in standorte]
    return (round(min(lat) - rand_grad, 1), round(max(lat) + rand_grad, 1),
            round(min(lon) - rand_grad, 1), round(max(lon) + rand_grad, 1))


# ------------------------------------------------------------------ Regen
def lies_vorhersage(antwort, standorte: list[dict]) -> dict[str, dict[str, float | None]]:
    """Open-Meteo antwortet bei mehreren Orten mit einer Liste in derselben Reihenfolge."""
    if isinstance(antwort, dict) and antwort.get("error"):
        raise AbrufFehler(f"Open-Meteo-Vorhersage meldet: {antwort.get('reason')}")
    liste = antwort if isinstance(antwort, list) else [antwort]
    if len(liste) != len(standorte):
        raise AbrufFehler(f"Open-Meteo-Vorhersage: {len(liste)} Antworten für {len(standorte)} Orte")
    ergebnis = {}
    for s, a in zip(standorte, liste):
        if not isinstance(a, dict) or a.get("error"):
            raise AbrufFehler(f"Open-Meteo-Vorhersage für {s['name']}: {a.get('reason') if isinstance(a, dict) else a}")
        taeglich = a.get("daily") or {}
        tage, werte = taeglich.get("time") or [], taeglich.get("precipitation_sum") or []
        if not tage or len(tage) != len(werte):
            raise AbrufFehler(f"Open-Meteo-Vorhersage ohne Tageswerte für {s['name']}")
        ergebnis[s["kennung"]] = dict(zip(tage, werte))
    return ergebnis


def hole_vorhersage(url: str, standorte: list[dict], vergangen: int = 7, voraus: int = 7) -> dict:
    """Tagesregen je Standort: die letzten `vergangen` Tage und die nächsten `voraus` Tage (Ortszeit China)."""
    params = {"latitude": ",".join(str(s["lat"]) for s in standorte),
              "longitude": ",".join(str(s["lon"]) for s in standorte),
              "daily": "precipitation_sum", "past_days": vergangen, "forecast_days": voraus,
              "timezone": "Asia/Shanghai"}
    return lies_vorhersage(netz.hole_json(url, params), standorte)
