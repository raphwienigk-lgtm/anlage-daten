"""Ersatz-Sensor Haselnuss → Select Harvests: Frostrechnung, Saisons, Rückblick, Stufe, Vorlesetext.

Erfundenes Klima: Frost 2004 und 2014 an drei Orten (stark), 2019 leichter Frost an zwei Orten,
2010 Frost nur an einem Ort (zählt nicht), 2025 absichtlich ohne Frost (der Sensor soll es verfehlen).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

import pytest

from anlage import konfig, logbuch, netz, speicher
from anlage.ausgabe import ersatz_text, vorlesen
from anlage.ersatz import __main__ as ersatz
from anlage.ersatz import frost
from anlage.quellen import openmeteo

FROST = {  # Jahr → (Tag, {Standort: Minimum})
    2004: ("04-03", {"ordu": -4.5, "giresun": -5.0, "trabzon": -3.5}),
    2014: ("03-30", {"ordu": -3.8, "giresun": -4.2, "samsun": -3.1}),
    2019: ("04-12", {"ordu": -1.5, "giresun": -1.2}),
    2010: ("03-20", {"duzce": -2.5}),
}
KURSSPRUNG = {date(2004, 4, 5), date(2014, 3, 31), date(2019, 4, 15)}   # erster Handelstag nach dem Frost


def _kennung(lat: float) -> str:
    k = ersatz.lade("haselnuss")
    return next(s["kennung"] for s in k["sensor"]["standorte"] if abs(s["lat"] - float(lat)) < 1e-6)


class Netz:
    def __init__(self, vorhersage_frost: bool = False, messung_2027: bool = False):
        self.vorhersage_frost = vorhersage_frost
        self.messung_2027 = messung_2027
        self.archiv_abrufe = 0

    def tmin(self, kennung: str, d: date) -> float:
        tag, orte = FROST.get(d.year, (None, {}))
        if tag and d.isoformat()[5:] == tag and kennung in orte:
            return orte[kennung]
        if self.messung_2027 and d == date(2027, 3, 15) and kennung in ("ordu", "giresun"):
            return -3.6
        return 3.0

    def hole_json(self, url, params=None, kopf=None, timeout=45):
        if "archive-api.open-meteo.com" in url:
            hoehen = [int(h) for h in str(params["elevation"]).split(",")]
            assert set(hoehen) <= {400, 100, 250}
            self.archiv_abrufe += 1
            start, ende = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
            tage = [start + timedelta(days=i) for i in range((ende - start).days + 1)]
            kennungen = [_kennung(lat) for lat in str(params["latitude"]).split(",")]
            antworten = [{"daily": {"time": [t.isoformat() for t in tage],
                                    "temperature_2m_min": [self.tmin(k, t) for t in tage]}} for k in kennungen]
            return antworten if len(antworten) > 1 else antworten[0]
        if url.startswith("https://api.open-meteo.com"):
            lats = params["latitude"].split(",")
            heute = date(2027, 3, 20)
            tage = [heute + timedelta(days=i) for i in range(-5, 10)]
            antworten = []
            for lat in lats:
                k = _kennung(lat)
                werte = [(-2.2 if self.vorhersage_frost and t == date(2027, 3, 24) and k in ("ordu", "giresun", "trabzon")
                          else 4.0) for t in tage]
                antworten.append({"daily": {"time": [t.isoformat() for t in tage], "temperature_2m_min": werte}})
            return antworten
        raise netz.AbrufFehler(f"Unbekannte Adresse im Test: {url}")


def falsche_kurse(ticker: str, zeitraum: str):
    reihe, wert, d = [], 1.0 if ticker == "SHV.AX" else 5000.0, date(2000, 1, 3)
    while d <= date(2027, 3, 19):
        if d.weekday() < 5:
            if ticker == "SHV.AX" and d in KURSSPRUNG:
                wert *= 1.25
            reihe.append({"datum": d.isoformat(), "schluss": round(wert, 4), "volumen": 3_000_000})
        d += timedelta(days=1)
    return reihe


@pytest.fixture
def ersatz_netz(monkeypatch):
    def einschalten(**kw):
        n = Netz(**kw)
        monkeypatch.setattr(netz, "hole_json", n.hole_json)
        monkeypatch.setattr(openmeteo, "drossel", lambda *a, **k: None)
        return n
    return einschalten


# ------------------------------------------------------------------ Einzelteile
def test_phase_und_naechte():
    s = ersatz.lade("haselnuss")["sensor"]
    assert frost.phase(date(2027, 3, 20), s) == "Saison"
    assert frost.phase(date(2027, 3, 1), s) == "Vorwarnung"
    assert frost.phase(date(2026, 9, 27), s) == "außer Saison"
    werte = {"a": {"2027-03-15": -3.5, "2027-03-16": -1.5}, "b": {"2027-03-15": -1.0, "2027-03-16": 0.5},
             "c": {"2027-03-15": -3.2, "2027-03-16": None}}
    n = frost.naechte(werte, -1.0, -3.0, 2)
    assert [x["datum"] for x in n] == ["2027-03-15"] and n[0]["orte"] == ["a", "b", "c"] and n[0]["stark"]
    assert n[0]["tiefste"] == -3.5


def test_formular_stimmig():
    k = ersatz.lade("haselnuss")
    assert k["rolle"] == "sensor" and k["ersatz"][0]["ticker"] == "SHV.AX"
    kennungen = [s["kennung"] for s in k["sensor"]["standorte"]]
    assert len(kennungen) == len(set(kennungen)) == 5
    assert k["sensor"]["stark_c"] < k["sensor"]["schwelle_c"] < 0


# ------------------------------------------------------------------ Ganzer Lauf
def test_ausser_saison_mit_rueckblick(ablage, ersatz_netz):
    ersatz_netz()
    zeit = datetime(2026, 9, 27, 4, 7, tzinfo=konfig.ZEITZONE)
    stand = ersatz.lauf("haselnuss", date(2026, 9, 27), zeit, budget_minuten=5, holen=falsche_kurse)
    assert stand["phase"] == "außer Saison" and stand["stufe"] == "Grün"
    assert stand["saisons_geladen"]["geladen"] == stand["saisons_geladen"]["von"] == 36
    a = stand["abgleich"]
    assert a["erkannte_jahre"] == [2004, 2014, 2019]
    assert a["bekannte_getroffen"] == [2004, 2014] and a["bekannte_verfehlt"] == [2025] and a["weitere"] == [2019]
    s2014 = next(s for s in stand["saisons"] if s["jahr"] == 2014)
    assert s2014["urteil"] == "starker Spätfrost" and s2014["erste"] == "2014-03-30" and s2014["tiefste"] == -4.2
    assert next(s for s in stand["saisons"] if s["jahr"] == 2019)["urteil"] == "Spätfrost"
    r = stand["rueckblick"]["SHV.AX"]
    assert r["urteil"] == "bestanden" and r["zusammen"]["n"] == 3 and r["zusammen"]["treffer"] == 3
    assert r["zusammen"]["v60"] == pytest.approx(0.25, abs=0.01)
    assert stand["preise"]["SHV.AX"]["urteil"] == "schläft"

    ersatz_text.schreibe(stand, konfig.ABGABE)
    gesamt = ""
    for t in sorted(konfig.ABGABE.glob("ersatz-haselnuss-teil-*.md")):
        text = t.read_text(encoding="utf-8")
        assert len(text) <= vorlesen.GRENZE
        rumpf = text.split("\n", 2)[2]
        assert not re.search(r"\d", rumpf), rumpf
        gesamt += rumpf
    assert "Stufe Grün. Außer Saison: Die Spätfrost-Saison läuft vom zehnten März bis zum dreißigsten April" in gesamt
    assert "Von den belegten Frostjahren erkennt er zweitausendvier und zweitausendvierzehn; verfehlt: zweitausendfünfundzwanzig." in gesamt
    assert "Treffer in drei Fällen. Nach der vorläufigen Regel bestanden." in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    assert "Stufe: Grün (außer Saison)" in (konfig.ABGABE / "status-ersatz-haselnuss.md").read_text(encoding="utf-8")

    # zweiter Lauf lädt keine Saison neu
    n = ersatz_netz()
    ersatz.lauf("haselnuss", date(2026, 9, 27), zeit, budget_minuten=5, holen=falsche_kurse)
    assert n.archiv_abrufe == 0


def test_saison_vorhersage_und_rot(ablage, ersatz_netz):
    zeit = datetime(2027, 3, 20, 4, 7, tzinfo=konfig.ZEITZONE)
    ersatz_netz(vorhersage_frost=True)
    stand = ersatz.lauf("haselnuss", date(2027, 3, 20), zeit, budget_minuten=5, holen=falsche_kurse)
    assert stand["phase"] == "Saison" and stand["stufe"] == "Gelb"
    assert stand["aktuell"]["vorhergesagt"][0]["datum"] == "2027-03-24"
    ersatz_text.schreibe(stand, konfig.ABGABE)
    text = (konfig.ABGABE / "ersatz-haselnuss-teil-1.md").read_text(encoding="utf-8")
    assert "Vorhergesagt ist eine Frostnacht, die erste am vierundzwanzigsten März in Giresun, Ordu und Trabzon" in text

    # gemessener starker Frost, Rückblick bestanden, Markt schläft → Rot
    ersatz_netz(messung_2027=True)
    stand = ersatz.lauf("haselnuss", date(2027, 3, 20), zeit, budget_minuten=5, holen=falsche_kurse)
    assert stand["stufe"] == "Rot" and stand["wechsel"] == {"vorher": "Gelb", "jetzt": "Rot"}
    assert stand["aktuell"]["gemessen"][0]["stark"]

    # Schattendepot: Rot kauft den Ersatz gedacht; das Ende der Ernte schließt
    assert stand["schattendepot"] == {"offen": True, "seit": "2027-03-20", "positionen": 1}
    o = konfig.DATEN / "ersatz" / "haselnuss"
    depot = speicher.lies_json(o / "schattendepot.json")
    assert depot["positionen"][0]["kurse"]["SHV.AX"]["datum"] == "2027-03-19"
    assert "^AXJO" in depot["positionen"][0]["vergleich"]
    stand = ersatz.lauf("haselnuss", date(2027, 3, 21), zeit, budget_minuten=5, holen=falsche_kurse)
    assert stand["schattendepot"]["positionen"] == 1                     # zweites Rot kauft nicht nach
    herbst = datetime(2027, 10, 1, 4, 7, tzinfo=konfig.ZEITZONE)
    stand = ersatz.lauf("haselnuss", date(2027, 10, 1), herbst, budget_minuten=5, holen=falsche_kurse)
    assert stand["stufe"] == "Grün" and stand["schattendepot"] == {"offen": False, "seit": None, "positionen": 1}
    assert speicher.lies_json(o / "schattendepot.json")["positionen"][0]["schluss_grund"] == "Ende der Ernte"
    verlauf = logbuch.lies(o / "verlauf.jsonl")
    assert [v["stufe"] for v in verlauf] == ["Gelb", "Rot", "Rot", "Grün"]


def test_frostjahr_haelt_gelb_bis_zur_ernte():
    saison = {"jahr": 2027, "urteil": "starker Spätfrost", "frostnaechte": 2, "tiefste": -4.0}
    stufe, gruende = ersatz.stufe_bestimmen("außer Saison", [], [], {}, {}, date(2027, 7, 1), saison)
    assert stufe == "Gelb" and gruende[0]["art"] == "frostjahr"
    stufe, _ = ersatz.stufe_bestimmen("außer Saison", [], [], {}, {}, date(2027, 10, 1), saison)
    assert stufe == "Grün"
