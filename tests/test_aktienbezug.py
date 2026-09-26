"""Aktienbezug: Korrelation, Mitnahme, Lauf mit erfundenen Kursen, Vorlesetext ohne Ziffern."""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

import pytest

from anlage import aktienbezug, konfig, speicher
from anlage.ausgabe import vorlesen


def test_korrelation_und_monatsmittel():
    assert aktienbezug.korrelation([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert aktienbezug.korrelation([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert aktienbezug.korrelation([1, 1, 1], [1, 2, 3]) is None
    tage = [{"datum": f"2026-01-{t:02d}", "schluss": 10.0 + t} for t in range(1, 21)]
    tage += [{"datum": "2026-02-02", "schluss": 99.0}]                    # zu wenige Kurse im Februar
    assert aktienbezug.monatsmittel(tage) == {2026 * 12: pytest.approx(20.5)}


def _preis(i: int) -> float:
    """Rohstoffpreis mit Zyklen: je vier Jahre auf und ab."""
    return 700 + 250 * math.sin(i / 8)


def _tage(von: date, bis: date, kurs) -> list[dict]:
    reihe, d = [], von
    while d <= bis:
        if d.weekday() < 5:
            reihe.append({"datum": d.isoformat(), "schluss": round(kurs(d), 4), "volumen": 1_000_000})
        d += timedelta(days=1)
    return reihe


def test_lauf_mit_erfundenen_kursen(ablage):
    heute = date(2026, 9, 26)
    monate = [(j, m) for j in range(2005, 2026) for m in range(1, 13)]
    speicher.schreibe_json(konfig.GESCHICHTE / "preise.json", {"reihen": {"palmoel": [
        {"datum": f"{j}-{m:02d}-01", "wert": round(_preis(j * 12 + m), 2)} for j, m in monate]}})

    def idx(d: date) -> int:
        return d.year * 12 + d.month

    kurse = {
        "F34.SI": lambda d: 3.0 + 0.001 * _preis(idx(d)),                      # hängt schwach am Preis
        "E5H.SI": lambda d: 0.2 * _preis(idx(d)) / 700,                         # folgt genau
        "EB5.SI": lambda d: 1.5 + 0.2 * math.sin(d.toordinal() / 50),           # eigener Takt
    }

    def holen(ticker, zeitraum):
        if ticker == "P8Z.SI":
            raise RuntimeError("gesperrt")
        return _tage(date(2008, 1, 1), date(2025, 12, 31), kurse[ticker])

    k = konfig.konfiguration()
    e = aktienbezug.rechne(k, heute, konfig.jetzt(), holen=holen)
    p = e["rohstoffe"]["palmoel"]
    nach = {a["ticker"]: a for a in p["aktien"]}
    assert nach["E5H.SI"]["korrelation_12"] > 0.95 and nach["E5H.SI"]["mitnahme"] == pytest.approx(1.0, abs=0.1)
    assert nach["EB5.SI"]["korrelation_12"] < 0.5
    assert p["reihenfolge"][0] == "E5H.SI" and "P8Z.SI" not in p["reihenfolge"]
    assert nach["P8Z.SI"]["status"] == "Fehler"
    assert nach["E5H.SI"]["stark_spannen"] > 0 and nach["E5H.SI"]["stark_mittel"] >= 0.2

    from anlage.ausgabe import aktienbezug_text
    aktienbezug_text.schreibe(e, konfig.ABGABE)
    teile = sorted(konfig.ABGABE.glob("aktienbezug-teil-*.md"))
    gesamt = ""
    for t in teile:
        text = t.read_text(encoding="utf-8")
        assert len(text) <= vorlesen.GRENZE
        rumpf = text.split("\n", 2)[2]
        assert not re.search(r"\d", rumpf), rumpf
        gesamt += rumpf
    assert "folgt am engsten Golden Agri-Resources, dann" in gesamt
    assert "Bumitama Agri (reinerer Plantagenwert): Die Kurse waren diesmal nicht abrufbar." in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    assert "Zustand: Warnung" in (konfig.ABGABE / "status-aktienbezug.md").read_text(encoding="utf-8")
