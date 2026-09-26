"""Metall-Agent China: Rechenwege und ein ganzer Lauf mit erfundenem Netz.

Die Szenarien sind erfunden. Sie prüfen nur, dass jeder Kanal die Achse richtig auf
Gelb setzt, der Rückblick rechnet und der Vorlesetext keine Ziffern enthält.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from anlage import konfig, netz
from anlage.ausgabe import metall_text, sprache, vorlesen
from anlage.metall import __main__ as metall
from anlage.metall import quellen as q
from anlage.metall import rechnen
from anlage.quellen import openmeteo

HEUTE = date(2026, 10, 20)


# ------------------------------------------------------------------ Einzelteile
def test_ausschreiben_und_abstand():
    assert sprache.ausschreiben("am 24.09.2026, Nr. 72 und Nr. 1/2026") == (
        "am vierundzwanzigsten September zweitausendsechsundzwanzig, Nummer zweiundsiebzig und "
        "Nummer eins aus dem Jahr zweitausendsechsundzwanzig")
    assert sprache.ausschreiben("15 CFR 744") == "fünfzehn CFR siebenhundertvierundvierzig"
    # Lengshuijiang – Hechi, rund 400 Kilometer
    assert 380 < q.abstand_km(27.69, 111.43, 24.69, 108.08) < 480


def test_fristen():
    k = metall.lade("china")
    f = {x["kennung"]: x for x in rechnen.fristen(k["fristen"], HEUTE, 30)}
    assert f["aussetzung_okt2025"]["tage"] == 21 and f["aussetzung_okt2025"]["gelb"]
    assert f["aussetzung_usa_ga_ge_sb"]["tage"] == 38 and not f["aussetzung_usa_ga_ge_sb"]["gelb"]
    spaet = {x["kennung"]: x for x in rechnen.fristen(k["fristen"], date(2026, 11, 12), 30)}
    assert spaet["aussetzung_okt2025"]["zustand"] == "abgelaufen" and spaet["aussetzung_okt2025"]["rot_pruefen"]
    verlaengert = [{**k["fristen"][0], "verlaengert_bis": date(2027, 1, 10)}]
    v = rechnen.fristen(verlaengert, date(2026, 11, 12), 30)[0]
    assert v["verlaengert"] and v["zustand"] == "läuft" and v["tage"] == 59


def test_ereignis_renditen():
    reihe = [{"datum": (date(2024, 1, 1) + timedelta(days=i)).isoformat(), "schluss": 10.0 + i} for i in range(100)]
    r = rechnen.ereignis_renditen(reihe, date(2024, 2, 1), [0, 5], 20)
    # Tag 0 ist der 1. Februar (Index 31), Basis der Vortag mit 40
    assert r["tag0"] == "2024-02-01" and r["r0"] == pytest.approx(41 / 40 - 1, abs=1e-4)
    assert r["r5"] == pytest.approx(46 / 40 - 1, abs=1e-4)
    assert r["vorlauf"] == pytest.approx(40 / 20 - 1, abs=1e-4)
    assert rechnen.ereignis_renditen(reihe, date(2023, 6, 1), [0], 20) is None      # damals nicht gehandelt
    assert rechnen.ereignis_renditen(reihe, date(2025, 6, 1), [0], 20) is None      # nach dem Ende


def test_trockenheit_und_normal():
    klima = {}
    for jahr in (1991, 1992):
        tage = {(date(jahr, 1, 1) + timedelta(days=i)).isoformat(): 2.0 for i in range(366 if jahr == 1992 else 365)}
        rechnen.klima_ergaenzen(klima, jahr, tage)
    ist = {(HEUTE - timedelta(days=i)).isoformat(): 0.8 for i in range(1, 91)}
    t = rechnen.trockenheit(ist, klima, 90, 0.6, 50)
    assert t["urteil"] == "trocken" and t["anteil"] == pytest.approx(0.4)
    feucht = rechnen.trockenheit({d: 2.2 for d in ist}, klima, 90, 0.6, 50)
    assert feucht["urteil"] == "normal" and not feucht["trocken"]
    trockenzeit = rechnen.trockenheit(ist, {"summen": {k: 0.1 * v for k, v in klima["summen"].items()},
                                            "anzahl": klima["anzahl"]}, 90, 0.6, 50)
    assert trockenzeit["urteil"] == "Trockenzeit"


def test_gegenseite_gewicht_und_achsen():
    k = metall.lade("china")
    bis = {"nummer": "2026-1", "titel": "Addition of Entities; Gallium Exports", "datum": "2026-10-10", "art": "Rule",
           "behoerden": ["commerce-department", "industry-and-security-bureau"], "zusammenfassung": ""}
    beirat = {"nummer": "2026-2", "titel": "Materials Technical Advisory Committee; Notice of Partially Closed Meeting",
              "datum": "2026-10-11", "art": "Notice", "behoerden": ["industry-and-security-bureau"],
              "zusammenfassung": "gallium"}
    innen = {"nummer": "2026-3", "titel": "Critical Mineral Mapping", "datum": "2026-10-12", "art": "Notice",
             "behoerden": ["interior-department"], "zusammenfassung": "Graphite deposits in Alaska"}
    zoll = {"nummer": "2026-4", "titel": "Active Anode Material From the People's Republic of China: Final Determination",
            "datum": "2026-10-13", "art": "Notice", "behoerden": ["commerce-department", "international-trade-administration"],
            "zusammenfassung": ""}
    d = rechnen.gegenseite({"gallium": [bis, beirat], "critical mineral": [innen, bis], "graphite": [zoll]},
                           k["gegenseite"], {"2026-1"})
    nach = {x["nummer"]: x for x in d}
    assert nach["2026-4"]["gewichtig"] and nach["2026-4"]["achsen"] == ["batterie"]
    assert len(d) == 4 and nach["2026-1"]["begriffe"] == ["gallium", "critical mineral"]
    assert nach["2026-1"]["gewichtig"] and not nach["2026-1"]["neu"]
    assert not nach["2026-2"]["gewichtig"] and nach["2026-2"]["neu"]
    assert nach["2026-3"]["achsen"] == ["batterie"] and not nach["2026-3"]["gewichtig"]


# ------------------------------------------------------------------ Ganzer Lauf
CHIP_VERSCHAERFUNG = [date(2023, 7, 3), date(2024, 8, 15), date(2024, 12, 3)]
CHIP_LOCKERUNG = [date(2025, 10, 30), date(2025, 11, 10)]


def _handelstage(von: date, bis: date):
    d = von
    while d <= bis:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _kurs(ticker: str, d: date) -> float:
    basis = {"PPTA": 5.0, "UAMY": 1.0, "MP": 20.0, "LYC.AX": 7.0, "XME": 50.0}[ticker]
    wert = basis * (1 + 0.02 * math.sin(d.toordinal() / 9))
    if ticker in ("PPTA", "UAMY"):
        for e in CHIP_VERSCHAERFUNG:
            if d >= e:
                wert *= 1.3
        for e in CHIP_LOCKERUNG:
            if d >= e:
                wert *= 0.85
    return wert


def falsche_kurse(ticker: str, zeitraum: str):
    assert zeitraum == "max"
    if ticker == "LYC.AX":
        raise RuntimeError("gesperrt")
    return [{"datum": d.isoformat(), "schluss": round(_kurs(ticker, d), 4), "volumen": 1000}
            for d in _handelstage(date(2021, 1, 4), HEUTE - timedelta(days=1))]


class Netz:
    """Erfundene Antworten für Bundesregister, USGS und Open-Meteo."""

    def __init__(self, trocken_anteil: float = 0.4):
        self.trocken_anteil = trocken_anteil
        self.abrufe = []

    def hole_json(self, url, params=None, kopf=None, timeout=45):
        self.abrufe.append(url)
        if "federalregister" in url:
            assert "industry-and-security-bureau" in params["conditions[agencies][]"]
            if params["conditions[term]"] == "gallium":
                return {"count": 2, "results": [
                    {"document_number": "2026-20001", "title": "Revisions to the Export Administration Regulations: "
                     "Gallium and Germanium Items", "publication_date": "2026-10-08", "type": "Rule",
                     "agencies": [{"name": "Commerce Department", "slug": "commerce-department"},
                                  {"name": "Industry and Security Bureau", "slug": "industry-and-security-bureau"}],
                     "html_url": "https://www.federalregister.gov/d/2026-20001", "abstract": "15 CFR 744"},
                    {"document_number": "2026-20002", "title": "Materials Technical Advisory Committee; Notice of "
                     "Partially Closed Meeting", "publication_date": "2026-10-09", "type": "Notice",
                     "agencies": [{"name": "Industry and Security Bureau", "slug": "industry-and-security-bureau"}]}]}
            return {"count": 0}
        if "earthquake.usgs.gov" in url:
            zeit = int(datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc).timestamp() * 1000)
            return {"type": "FeatureCollection", "features": [
                {"id": "us1", "properties": {"mag": 6.1, "place": "Yunnan, China", "time": zeit, "url": "x"},
                 "geometry": {"coordinates": [100.9, 23.9, 10.0]}},          # rund 85 km von Lincang
                {"id": "us2", "properties": {"mag": 5.2, "place": "Sichuan, China", "time": zeit, "url": "y"},
                 "geometry": {"coordinates": [104.0, 30.0, 10.0]}}]}          # weit weg von allen
        if url.startswith("https://api.open-meteo.com"):
            anzahl = len(params["latitude"].split(","))
            tage = [(HEUTE + timedelta(days=i)).isoformat() for i in range(-7, 7)]
            antworten = []
            for nr in range(anzahl):
                regen = [5.0] * len(tage)
                if nr == 1:                    # Hechi: gemessener Starkregen vor drei Tagen
                    regen[4] = 130.0
                if nr == 7:                    # Ganzhou: Starkregen vorhergesagt
                    regen[10] = 110.0
                antworten.append({"daily": {"time": tage, "precipitation_sum": regen}})
            return antworten
        if "archive-api.open-meteo.com" in url:
            start, ende = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
            tage = [start + timedelta(days=i) for i in range((ende - start).days + 1)]
            normal = start.year <= 2020
            werte = []
            for t in tage:
                if normal:
                    werte.append(3.0)
                elif (HEUTE - t).days <= 5:
                    werte.append(None)          # ERA5 liegt einige Tage zurück
                else:
                    werte.append(3.0 * (self.trocken_anteil if params["latitude"] == 25.49 else 1.0))
            return {"daily": {"time": [t.isoformat() for t in tage], "precipitation_sum": werte}}
        raise netz.AbrufFehler(f"Unbekannte Adresse im Test: {url}")


@pytest.fixture
def metall_netz(monkeypatch):
    falsch = Netz()
    monkeypatch.setattr(netz, "hole_json", falsch.hole_json)
    monkeypatch.setattr(openmeteo, "drossel", lambda *a, **k: None)
    return falsch


def test_ganzer_lauf(ablage, metall_netz):
    zeit = datetime(2026, 10, 20, 1, 17, tzinfo=konfig.ZEITZONE)
    stand = metall.lauf("china", HEUTE, zeit, budget_minuten=5, holen=falsche_kurse)
    a = stand["achsen"]

    chip = {g["kanal"] for g in a["chip"]["gruende"]}
    assert chip == {"gegenseite", "erdbeben", "starkregen", "trocken"} and a["chip"]["stufe"] == "Gelb"
    assert a["chip"]["mehrfach"]
    assert {g["kanal"] for g in a["magnet"]["gruende"]} == {"frist", "starkregen"}    # Ganzhou vorhergesagt
    assert [g["kanal"] for g in a["batterie"]["gruende"]] == ["frist"]
    assert a["werkzeug"]["stufe"] == "Gelb"                                             # Ganzhou auch Wolfram
    assert stand["reihenfolge"][0] == "magnet" or stand["reihenfolge"][0] == "chip"

    beben = stand["stoerung"]["erdbeben"]
    assert len(beben) == 1 and beben[0]["standort"] == "lincang" and 60 < beben[0]["abstand_km"] < 110
    assert stand["stoerung"]["trocken"]["qujing"]["urteil"] == "trocken"
    assert stand["stoerung"]["trocken"]["lincang"]["urteil"] == "normal"
    doks = stand["gegenseite"]["dokumente"]
    assert [d["gewichtig"] for d in doks] == [False, True]

    p = stand["preise"]
    assert p["PPTA"]["urteil"] == "schläft" and p["LYC.AX"]["urteil"] == "keine Kurse"
    assert p["PPTA"]["duenn"] is True and 5000 < p["PPTA"]["handel"] < 10000
    assert stand["quellen"]["yahoo"]["status"] == "Warnung" and stand["zustand"] == "Warnung"

    r = stand["rueckblick"]
    assert r["PPTA"]["urteil"] == "bestanden"
    g = r["PPTA"]["gruppen"]
    assert g["verschaerfung_eigene"]["n"] == 3 and g["verschaerfung_eigene"]["treffer"] == 3
    assert g["verschaerfung_eigene"]["v20"] == pytest.approx(0.3, abs=0.05)
    assert g["lockerung_eigene"]["n"] == 2 and g["lockerung_eigene"]["treffer"] == 2
    assert r["MP"]["urteil"] in ("nicht bestanden", "zu wenige Fälle")

    # Archiv und Protokoll liegen an ihrem Platz
    o = konfig.DATEN / "metall" / "china"
    assert (o / "kurse" / "PPTA.csv").exists() and (o / "rueckblick.json").exists()
    assert (o / "klima" / "qujing.json").exists()
    assert [e["standort"] for e in json.loads((o / "stoerungen.json").read_text())] == ["hechi"]

    metall_text.schreibe(stand, konfig.ABGABE)
    teile = sorted(konfig.ABGABE.glob("metall-china-teil-*.md"))
    gesamt = ""
    for t in teile:
        text = t.read_text(encoding="utf-8")
        assert len(text) <= vorlesen.GRENZE
        rumpf = text.split("\n", 2)[2]
        assert not re.search(r"\d", rumpf), rumpf
        gesamt += rumpf
    assert "Chip-Achse, der Pilot: Gelb. Anlässe: US-Maßnahme vom achten Oktober; Erdbeben bei Lincang; Starkregen in Hechi; Trockenheit in Qujing." in gesamt
    assert "Erdbeben der Stärke sechs Komma eins am zwölften Oktober" in gesamt
    assert "Bekanntmachung Nummer siebzig) läuft am zehnten November aus, in einundzwanzig Tagen" in gesamt
    assert "Perpetua Resources: nach Verschärfungen auf der eigenen Achse in drei Fällen" in gesamt
    assert "Dollar am Tag, das ist dünn." in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    status = (konfig.ABGABE / "status-metall-china.md").read_text(encoding="utf-8")
    assert "Zustand: Warnung" in status and "Chip-Achse Gelb" in status

    # Zweiter Lauf: kein Wechsel, das Dokument ist nicht mehr neu, das Normal wird nicht neu geladen
    vorher = len([u for u in metall_netz.abrufe if "archive" in u])
    stand2 = metall.lauf("china", HEUTE, zeit, budget_minuten=5, holen=falsche_kurse)
    assert not stand2["wechsel"] and not any(d["neu"] for d in stand2["gegenseite"]["dokumente"])
    assert len([u for u in metall_netz.abrufe if "archive" in u]) - vorher == 2      # nur die zwei aktuellen Fenster


def test_normal_wird_geladen_und_quellen_fallen_aus(ablage, monkeypatch):
    def kaputt(url, params=None, kopf=None, timeout=45):
        raise netz.AbrufFehler(f"Fehler 503 bei {url}")
    monkeypatch.setattr(netz, "hole_json", kaputt)
    monkeypatch.setattr(openmeteo, "drossel", lambda *a, **k: None)
    zeit = datetime(2026, 10, 20, 1, 17, tzinfo=konfig.ZEITZONE)
    stand = metall.lauf("china", HEUTE, zeit, budget_minuten=0, holen=falsche_kurse)
    assert stand["stoerung"]["trocken"]["qujing"]["urteil"] == "Normal wird geladen"
    assert stand["quellen"]["bundesregister"]["status"] == "Fehler"
    assert stand["achsen"]["chip"]["stufe"] == "Grün"            # Fristen allein: Chip noch nicht in Reichweite
    metall_text.schreibe(stand, konfig.ABGABE)
    text = (konfig.ABGABE / "metall-china-teil-1.md").read_text(encoding="utf-8")
    assert "Das Regen-Normal wird noch geladen, bisher null von dreißig Jahren." in text
    assert "Nicht erreichbar:" in text


def test_formular_stimmig():
    """Jede Achse, jedes Metall und jeder Standort im Formular verweist auf etwas, das es gibt."""
    k = metall.lade("china")
    achsen, metalle = set(k["achsen"]), set(k["metalle"])
    assert all(m["achse"] in achsen for m in k["metalle"].values())
    assert all(set(a["metalle"]) <= metalle for a in k["achsen"].values())
    assert all(set(s["metalle"]) <= metalle for s in k["standorte"])
    assert all(i["achse"] in achsen and i["rolle"] in ("kandidat", "beobachtung") for i in k["instrumente"])
    assert all(set(f["achsen"]) <= achsen for f in k["fristen"])
    assert all(set(e["achsen"]) <= achsen and e["art"] in ("verschaerfung", "lockerung", "gegenseite")
               for e in k["ereignisse"])
    assert all(set(v) <= achsen for v in k["gegenseite"]["begriffe"].values())
    assert sum(1 for a in k["achsen"].values() if a.get("pilot")) == 1
    for e in k["ereignisse"]:
        assert rechnen.tag(e["datum"]).weekday() < 5, f"{e['datum']} ist ein Wochenende"


def test_handel():
    reihe = [{"datum": f"2026-01-{i:02d}", "schluss": 2.0, "volumen": 1_000_000 * (i % 3 + 1)} for i in range(1, 31)]
    h = rechnen.handel(reihe, 30, 1_000_000)
    assert h == {"handel": 4_000_000, "duenn": False}
    assert rechnen.handel(reihe[:5], 30, 1_000_000) == {"handel": None, "duenn": None}
