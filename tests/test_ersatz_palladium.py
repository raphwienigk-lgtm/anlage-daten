"""Ersatz-Paar Palladium → Platin: Signale am Original, Stufe, Rückblick, Schattendepot, Vorlesetext.

Erfunden: Palladium steigt 2012, 2015, 2019 und im September 2026 binnen zwanzig Handelstagen um mehr als
dreißig Prozent. Platin springt jeweils sechs Wochen nach Beginn des Anstiegs um 25 Prozent, zuletzt noch
nicht. Gold bleibt flach.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from anlage import konfig, speicher
from anlage.ausgabe import ersatz_text, vorlesen
from anlage.ersatz import __main__ as ersatz
from anlage.ersatz import preis

S = {"anstieg_tage": 60, "anstieg_ab": 0.30, "verhaeltnis_ab": 1.0, "pause_tage": 120}
RAMPEN = [(date(2012, 3, 1), 50, 70), (date(2015, 6, 1), 70, 95), (date(2019, 1, 2), 95, 130), (date(2026, 9, 1), 130, 175)]


def _tage(von: date, bis: date) -> list[date]:
    tage, d = [], von
    while d <= bis:
        if d.weekday() < 5:
            tage.append(d)
        d += timedelta(days=1)
    return tage


def _reihe(werte: list[tuple[date, float]]) -> list[dict]:
    return [{"datum": d.isoformat(), "schluss": round(w, 4), "volumen": 2_000_000} for d, w in werte]


def falsche_kurse(ticker: str, zeitraum: str):
    tage = _tage(date(2010, 1, 4), date(2027, 3, 26))
    if ticker == "GLD":
        return _reihe([(d, 180.0) for d in tage])
    if ticker == "PA=F":
        werte, stand = [], 50.0
        for d in tage:
            for beginn, von, bis in RAMPEN:
                i = sum(1 for t in tage if beginn <= t <= d)
                if 0 < i <= 20:
                    stand = von + (bis - von) * i / 20
            werte.append((d, stand))
        return _reihe(werte)
    if ticker in ("PPLT", "PL=F"):
        spruenge = [beginn + timedelta(days=42) for beginn, _, _ in RAMPEN[:3]]
        return _reihe([(d, 150.0 * 1.25 ** sum(1 for s in spruenge if d >= s)) for d in tage])
    raise AssertionError(ticker)


def bis(tag: str):
    return lambda ticker, zeitraum: [e for e in falsche_kurse(ticker, zeitraum) if e["datum"] <= tag]


def test_signale_und_verhaeltnis():
    tage = _tage(date(2020, 1, 1), date(2021, 12, 31))
    pall = _reihe([(d, 80.0 if i < 200 else 104.0) for i, d in enumerate(tage)])      # +30 % in einem Schritt
    pplt = _reihe([(d, 100.0) for d in tage])
    liste = preis.signale(pall, pplt, S)
    assert [x["art"] for x in liste] == ["Sprung"] and liste[0]["verhaeltnis"] == 1.04   # Sprung geht vor, Pause schluckt das Verhältnis
    pall = _reihe([(d, 90.0 if i < 200 else 101.0) for i, d in enumerate(tage)])      # nur +12 %, aber teurer als Platin
    liste = preis.signale(pall, pplt, S)
    assert [(x["art"], x["wert"]) for x in liste] == [("Verhältnis", 1.01)]
    assert preis.lage(pall, pplt, S) == {"datum": tage[-1].isoformat(), "anstieg": 0.0, "verhaeltnis": 1.01}


def test_ganzer_lauf_rot_und_schattendepot(ablage):
    zeit = datetime(2026, 9, 25, 4, 7, tzinfo=konfig.ZEITZONE)
    stand = ersatz.lauf("palladium", date(2026, 9, 25), zeit, holen=bis("2026-09-25"))
    assert [x["art"] for x in stand["signale"]] == ["Sprung"] * 4
    assert [x["datum"][:4] for x in stand["signale"]] == ["2012", "2015", "2019", "2026"]
    r = stand["rueckblick"]["PPLT"]
    assert r["urteil"] == "bestanden" and r["zusammen"]["n"] == 3 and r["zusammen"]["treffer"] == 3
    assert stand["preise"]["PPLT"]["urteil"] == "schläft"
    assert stand["stufe"] == "Rot" and stand["schattendepot"] == {"offen": True, "seit": "2026-09-25", "positionen": 1}

    ersatz_text.schreibe(stand, konfig.ABGABE)
    gesamt = ""
    for t in sorted(konfig.ABGABE.glob("ersatz-palladium-teil-*.md")):
        text = t.read_text(encoding="utf-8")
        assert len(text) <= vorlesen.GRENZE
        rumpf = text.split("\n", 2)[2]
        assert not re.search(r"\d", rumpf), rumpf
        gesamt += rumpf
    assert "Stufe Rot. Letztes Signal am" in gesamt and "Palladium ist binnen sechzig Handelstagen um" in gesamt
    assert ("Seit zweitausendzehn meldete der Sensor vier Signale: zweitausendzwölf (Sprung), zweitausendfünfzehn (Sprung), "
            "zweitausendneunzehn (Sprung) und zweitausendsechsundzwanzig (Sprung).") in gesamt
    assert "Platin-ETF nach drei Signalen, gerechnet ab dem Tag nach dem Signal: nach einhundertzwanzig Handelstagen" in gesamt
    assert "Hier sind beide handelbar; der Sensor ist der Preis des Originals." in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    assert "Stufe: Rot (ganzjährig)" in (konfig.ABGABE / "status-ersatz-palladium.md").read_text(encoding="utf-8")

    # ein halbes Jahr später: Signal abgelaufen, gedachte Position geschlossen
    spaeter = datetime(2027, 3, 26, 4, 7, tzinfo=konfig.ZEITZONE)
    stand = ersatz.lauf("palladium", date(2027, 3, 26), spaeter, holen=bis("2027-03-26"))
    assert stand["stufe"] == "Grün" and stand["gruende"][0]["art"] == "ruhig"
    depot = speicher.lies_json(konfig.DATEN / "ersatz" / "palladium" / "schattendepot.json")
    assert depot["positionen"][0]["schluss_grund"] == "nach 180 Tagen"
    ersatz_text.schreibe(stand, konfig.ABGABE)
    text = (konfig.ABGABE / "ersatz-palladium-teil-1.md").read_text(encoding="utf-8")
    assert "Stufe Grün. Palladium ist in sechzig Handelstagen" in text and "mal so viel wie Platin" in text


def test_main_laeuft_alle_sensoren(ablage, monkeypatch):
    aufgerufen = []
    monkeypatch.setattr(ersatz, "lauf", lambda kennung, *a, **k: aufgerufen.append(kennung) or (_ for _ in ()).throw(RuntimeError("Test")))
    assert ersatz.main(["--heute", "2026-09-27"]) == 1                    # beide abgebrochen: Fehler
    assert aufgerufen == ["haselnuss", "palladium"]


def test_verhaeltnis_aus_den_metallpreisen_nicht_aus_den_etf(ablage):
    """Erster echter Lauf: Das Verhältnis der bereinigten ETF-Kurse lag beim Doppelten des Metallverhältnisses
    und zeigte Palladium fälschlich teurer als Platin."""
    tage = _tage(date(2025, 1, 2), date(2026, 9, 25))
    werte = {"PA=F": 1200.0, "PL=F": 1500.0, "PPLT": 15.0, "GLD": 380.0}
    holen = lambda ticker, zeitraum: _reihe([(d, werte[ticker]) for d in tage])
    stand = ersatz.lauf("palladium", date(2026, 9, 25), datetime(2026, 9, 25, 4, 7, tzinfo=konfig.ZEITZONE), holen=holen)
    assert stand["lage"]["verhaeltnis"] == 0.8 and stand["stufe"] == "Grün"
