"""Kurse und Rohstoffpreise.

- FRED (Federal Reserve St. Louis) liefert IMF-Monatspreise, etwa Palmöl PPOILUSDM.
- yfinance liest Tageskurse mit Volumen von Yahoo Finance. Das ist eine inoffizielle
  Schnittstelle; bei Sperren fehlt der Wert für diesen Tag, der Lauf geht weiter.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from .. import netz
from ..netz import AbrufFehler


def lies_fred_csv(text: str) -> list[dict]:
    """FRED-CSV mit Spalten DATE bzw. observation_date und der Serie. '.' ist ein Fehlwert."""
    zeilen = list(csv.reader(io.StringIO(text)))
    if len(zeilen) < 2:
        raise AbrufFehler("FRED-Datei ist leer")
    reihe = []
    for zeile in zeilen[1:]:
        if len(zeile) < 2:
            continue
        datum, wert = zeile[0], zeile[1]
        if not wert or wert == ".":
            continue
        try:
            reihe.append({"datum": datum[:10], "wert": float(wert)})
        except ValueError:
            continue
    if not reihe:
        raise AbrufFehler("FRED-Datei ohne Werte")
    return reihe


def hole_fred(url: str, serie: str) -> list[dict]:
    return lies_fred_csv(netz.hole_text(url, {"id": serie}))


def tabelle_zu_reihe(tabelle, jetzt=None) -> list[dict]:
    """Wandelt die yfinance-Tabelle in {'datum', 'schluss', 'volumen'} um.

    Zeilen des laufenden Handelstags werden weggelassen: Um 02:30 UTC ist in Singapur
    Handelszeit, der Kurs des Tages steht noch nicht fest. Als abgeschlossen gilt ein Tag
    ab 18 Uhr Ortszeit der Börse (Zeitzone aus der Tabelle).
    """
    zone = getattr(tabelle.index, "tz", None)
    if jetzt is None and zone is not None:
        jetzt = datetime.now(zone)
    reihe = []
    for zeitpunkt, zeile in tabelle.iterrows():
        tag = zeitpunkt.date()
        if jetzt is not None and (tag > jetzt.date() or (tag == jetzt.date() and jetzt.hour < 18)):
            continue
        schluss = zeile.get("Close")
        if schluss is None or schluss != schluss:  # NaN
            continue
        volumen = zeile.get("Volume")
        gueltig = volumen is not None and volumen == volumen and volumen > 0
        reihe.append({
            "datum": tag.isoformat(),
            "schluss": round(float(schluss), 4),
            "volumen": int(volumen) if gueltig else None,
        })
    return reihe


def hole_yahoo(ticker: str, zeitraum: str = "2y") -> list[dict]:
    """Tageskurse als Liste von {'datum', 'schluss', 'volumen'}, nur abgeschlossene Tage.

    zeitraum wie bei yfinance: 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max.
    """
    try:
        import yfinance as yf
    except ImportError as fehler:
        raise AbrufFehler("yfinance ist nicht installiert") from fehler
    try:
        tabelle = yf.Ticker(ticker).history(period=zeitraum, auto_adjust=False)
    except Exception as fehler:  # yfinance wirft je nach Version verschiedene Fehler
        raise AbrufFehler(f"Yahoo für {ticker}: {type(fehler).__name__}: {fehler}") from fehler
    if tabelle is None or tabelle.empty:
        raise AbrufFehler(f"Yahoo lieferte keine Kurse für {ticker}")
    reihe = tabelle_zu_reihe(tabelle)
    if not reihe:
        raise AbrufFehler(f"Yahoo lieferte nur leere Zeilen für {ticker}")
    return reihe


# ---------------------------------------------------------------- Preisarchiv
FELDER = ["datum", "schluss", "volumen"]


def lies_archiv(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    with open(pfad, encoding="utf-8") as f:
        reihe = []
        for zeile in csv.DictReader(f):
            reihe.append({
                "datum": zeile["datum"],
                "schluss": float(zeile["schluss"]),
                "volumen": int(zeile["volumen"]) if zeile.get("volumen") else None,
            })
        return reihe


def ergaenze_archiv(pfad: Path, neu: list[dict]) -> list[dict]:
    """Führt neue Kurse ins Archiv. Neuere Werte ersetzen ältere am selben Tag."""
    nach_datum = {e["datum"]: e for e in lies_archiv(pfad)}
    for eintrag in neu:
        nach_datum[eintrag["datum"]] = eintrag
    reihe = [nach_datum[d] for d in sorted(nach_datum)]
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=FELDER)
        schreiber.writeheader()
        for e in reihe:
            schreiber.writerow({k: ("" if e.get(k) is None else e.get(k)) for k in FELDER})
    return reihe


def archiv_pfad(ordner: Path, ticker: str) -> Path:
    sicher = "".join(z if z.isalnum() else "_" for z in ticker)
    return ordner / f"{sicher}.csv"
