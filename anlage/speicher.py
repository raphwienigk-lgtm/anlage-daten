"""Lesen und Schreiben der Dateien unter daten/ und abgabe/.

Geschrieben wird immer erst in eine Hilfsdatei, dann umbenannt. So bleibt bei einem
Abbruch mitten im Schreiben die alte Datei heil.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path


def lies_json(pfad: Path, standard=None):
    """Liest eine JSON-Datei. Fehlt sie oder ist sie beschädigt, kommt `standard` zurück."""
    if not pfad.exists():
        return standard
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as fehler:
        print(f"Warnung: {pfad.name} ist beschädigt und wird ignoriert ({fehler})")
        return standard


def schreibe_json(pfad: Path, daten, kompakt: bool = False) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    hilfe = pfad.with_suffix(pfad.suffix + ".neu")
    with open(hilfe, "w", encoding="utf-8") as f:
        if kompakt:
            json.dump(daten, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(daten, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    os.replace(hilfe, pfad)


def schreibe_text(pfad: Path, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    hilfe = pfad.with_suffix(pfad.suffix + ".neu")
    hilfe.write_text(text, encoding="utf-8")
    os.replace(hilfe, pfad)


# ------------------------------------------------------------------ Regenarchiv
def regen_abrufbeginn(vorhanden: dict[str, float | None], bedarf_ab: date, heute: date,
                      nachlauf_tage: int = 100) -> date:
    """Ab welchem Tag ein Punkt neu geholt werden muss.

    Ist das Archiv lückenlos bis zum Bedarf gefüllt, genügen die letzten `nachlauf_tage`
    (ERA5 korrigiert vorläufige Werte der letzten Wochen noch nachträglich).
    """
    gemessen = sorted(d for d, w in vorhanden.items() if w is not None)
    if not gemessen or date.fromisoformat(gemessen[0]) > bedarf_ab:
        return bedarf_ab
    letzter = date.fromisoformat(gemessen[-1])
    start = min(heute - timedelta(days=nachlauf_tage), letzter - timedelta(days=10))
    return max(start, bedarf_ab)


def regen_zusammenfuehren(vorhanden: dict, neu: dict, behalten_ab: date) -> dict:
    """Neue Werte ersetzen alte; ein neuer Fehlwert (None) löscht keinen alten Messwert."""
    ergebnis = dict(vorhanden)
    for datum, wert in neu.items():
        if wert is not None or datum not in ergebnis:
            ergebnis[datum] = wert
    grenze = behalten_ab.isoformat()
    return {d: ergebnis[d] for d in sorted(ergebnis) if d >= grenze}
