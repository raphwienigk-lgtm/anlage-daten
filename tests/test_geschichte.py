"""Geschichtsdaten: Pink Sheet, USDA PSD, fortsetzbarer Regen- und Windabruf."""
from __future__ import annotations

import io
import zipfile
from datetime import date

import openpyxl
import pytest

from anlage import geschichte, konfig, netz, speicher
from anlage.klimatologie import Abbruch
from anlage.netz import AbrufFehler
from anlage.quellen import kurse

from conftest import WIND_NORMAL, Szenario, _monate


def pink_sheet(von=(1960, 1), bis=(1962, 12), luecke_brent_bis=(1960, 6)) -> bytes:
    """Nachbau des Blatts „Monthly Prices“: Titelzeilen, Kopfzeile, Einheiten, Daten 1960M01."""
    mappe = openpyxl.Workbook()
    blatt = mappe.active
    blatt.title = "Monthly Prices"
    blatt.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    blatt.append(["Updated on September 02, 2026"])
    blatt.append([])
    blatt.append(["", "Crude oil, average", "Crude oil, Brent ", "Palm kernel oil", "Palm oil", "Soybean oil"])
    blatt.append(["", "($/bbl)", "($/bbl)", "($/mt)", "($/mt)", "($/mt)"])
    for i, (j, m) in enumerate(_monate(von, bis)):
        brent = "…" if (j, m) <= luecke_brent_bis else 1.5 + i / 100
        blatt.append([f"{j}M{m:02d}", 1.6, brent, 999.0, 200.0 + i, 300.0 + i])
    blatt.append(["Description"])
    puffer = io.BytesIO()
    mappe.save(puffer)
    return puffer.getvalue()


SPALTEN = {"palmoel": "Palm oil", "brent": "Crude oil, Brent", "sojaoel": "Soybean oil"}


def test_pink_sheet_liest_spalten_und_ueberspringt_fehlwerte():
    reihen, fehlend = geschichte.lies_weltbank(pink_sheet(), SPALTEN)
    assert fehlend == []
    assert reihen["palmoel"][0] == {"datum": "1960-01-01", "wert": 200.0}
    assert reihen["palmoel"][-1] == {"datum": "1962-12-01", "wert": 235.0}
    assert len(reihen["palmoel"]) == 36
    assert reihen["brent"][0]["datum"] == "1960-07-01"          # „…“ ist ein Fehlwert
    assert reihen["sojaoel"][5]["wert"] == 305.0                # nicht mit Palmkernöl verwechselt


def test_pink_sheet_meldet_fehlende_spalte():
    reihen, fehlend = geschichte.lies_weltbank(pink_sheet(), {**SPALTEN, "kakao": "Cocoa"})
    assert fehlend == ["kakao"]
    assert set(reihen) == {"palmoel", "brent", "sojaoel"}


def test_preise_aus_pink_sheet(ablage, monkeypatch):
    k = konfig.konfiguration()
    inhalt = pink_sheet()
    monkeypatch.setattr(netz, "hole_bytes", lambda url, params=None, timeout=120: inhalt)
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: (_ for _ in ()).throw(AbrufFehler("aus")))
    daten = geschichte.preise(k, melde=lambda t: None)
    assert daten["herkunft"]["palmoel"].startswith("Weltbank Pink Sheet")
    gespeichert = speicher.lies_json(konfig.GESCHICHTE / "preise.json")
    assert gespeichert["reihen"]["palmoel"][0]["datum"] == "1960-01-01"


def test_preise_rueckfall_fred(ablage, monkeypatch):
    k = konfig.konfiguration()

    def kaputt(url, params=None, timeout=120):
        raise AbrufFehler("Fehler 404")

    monkeypatch.setattr(netz, "hole_bytes", kaputt)
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: (_ for _ in ()).throw(AbrufFehler("aus")))
    monkeypatch.setattr(kurse, "hole_fred", lambda url, serie: [{"datum": "1992-01-01", "wert": 1.0}])
    daten = geschichte.preise(k, melde=lambda t: None)
    assert daten["herkunft"]["palmoel"] == "FRED PPOILUSDM (erst ab 1992)"
    assert any("404" in f for f in daten["fehler"])


def psd_zip() -> bytes:
    kopf = ("Commodity_Code,Commodity_Description,Country_Code,Country_Name,Market_Year,Calendar_Year,Month,"
            "Attribute_ID,Attribute_Description,Unit_ID,Unit_Description,Value")
    zeilen = [kopf,
              '4243000,"Oil, Palm",ID,Indonesia,1997,2020,10,28,Production,21,(1000 MT),5380',
              '4243000,"Oil, Palm",ID,Indonesia,1998,2020,10,28,Production,21,(1000 MT),5930',
              '4243000,"Oil, Palm",MY,Malaysia,1998,2020,10,28,Production,21,(1000 MT),8319',
              '4243000,"Oil, Palm",MY,Malaysia,1998,2020,10,88,Exports,21,(1000 MT),7000',
              '4243000,"Oil, Palm",TH,Thailand,1998,2020,10,28,Production,21,(1000 MT),470',
              '4232000,"Oil, Soybean",ID,Indonesia,1998,2020,10,28,Production,21,(1000 MT),1']
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as archiv:
        archiv.writestr("psd_oilseeds.csv", "﻿" + "\n".join(zeilen) + "\n")
    return puffer.getvalue()


def test_psd_liest_nur_produktion_der_laender():
    reihen = geschichte.lies_psd(psd_zip(), "Oil, Palm", ["Indonesia", "Malaysia"])
    assert reihen == {"Indonesia": {"1997": 5380.0, "1998": 5930.0}, "Malaysia": {"1998": 8319.0}}


def test_abschnitte():
    ost = geschichte._abschnitte_ost(date(1959, 10, 1), date(1966, 2, 23))
    assert [m for _, _, m in ost] == ["1959-1959", "1960-1964", "1965-1969"]
    assert ost[0][:2] == (date(1959, 10, 1), date(1959, 12, 31))
    assert ost[-1][1] == date(1966, 2, 23)
    west = geschichte._abschnitte_west(date(1959, 10, 1), date(1966, 2, 23))
    assert [m for _, _, m in west] == [str(j) for j in range(1959, 1966)]
    assert west[0][:2] == (date(1959, 10, 1), date(1959, 12, 31))


def test_regen_haelt_am_budget_an_und_macht_weiter(ablage, netz_mit):
    k = konfig.konfiguration()
    heute = date(1966, 3, 1)
    falsch = netz_mit(Szenario(heute=heute))
    with pytest.raises(Abbruch):
        geschichte.regen(k, geschichte.Budget(200, 60, 0), heute, melde=lambda t: None)
    erster = k["regionen"]["ost"]["punkte"][0]["name"]
    zweiter = k["regionen"]["ost"]["punkte"][1]["name"]
    d1 = geschichte.lies_gz(geschichte.regen_pfad(erster))
    d2 = geschichte.lies_gz(geschichte.regen_pfad(zweiter))
    assert d1["fertig"] == ["1959-1959", "1960-1964"]          # jüngster Block bleibt offen für Nachträge
    assert d2["fertig"] == ["1959-1959"]
    assert d1["werte"]["1962-05-05"] == 8.0

    vorher = len(falsch.abrufe)
    stand = geschichte.regen(k, geschichte.Budget(10_000, 60, 0), heute, melde=lambda t: None)
    neu = falsch.abrufe[vorher:]
    starts = [(p["latitude"], p["start_date"]) for _, p in neu]
    punkt1 = k["regionen"]["ost"]["punkte"][0]
    assert (punkt1["lat"], "1960-01-01") not in starts           # fertige Blöcke nicht doppelt
    assert (punkt1["lat"], "1965-01-01") in starts               # offener Block wird erneuert
    west = k["regionen"]["west"]["punkte"][0]["name"]
    assert stand[west]["von"] == "1959-10-01"
    assert all(d[5:7] in ("10", "11", "12") for d in geschichte.lies_gz(geschichte.regen_pfad(west))["werte"])


def test_wind_ueberspringt_jahre_der_klimatologie(ablage, netz_mit):
    k = konfig.konfiguration()
    heute = date(1962, 9, 1)
    falsch = netz_mit(Szenario(heute=heute, wind_jahr_stark=1961))
    punkte = k["regionen"]["wind_sumatra"]["punkte"]
    speicher.schreibe_json(konfig.KLIMA / "wind.json", {
        "punkte": {p["name"]: {"mittel_ms": -3.0, "je_jahr": {"1960": -3.0}} for p in punkte}})
    daten = geschichte.wind(k, geschichte.Budget(1000, 60, 0), heute, melde=lambda t: None)
    je_jahr = daten["punkte"][punkte[0]["name"]]["je_jahr"]
    assert set(je_jahr) == {"1961", "1962"}
    assert je_jahr["1961"] == pytest.approx(WIND_NORMAL - 1.5)
    assert len(falsch.abrufe) == 4


def test_hauptlauf_schreibt_status(ablage, monkeypatch):
    inhalt = pink_sheet()
    monkeypatch.setattr(netz, "hole_bytes", lambda url, params=None, timeout=120: inhalt)
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: (_ for _ in ()).throw(AbrufFehler("aus")))
    assert geschichte.main(["--nur", "preise", "--heute", "2026-09-26"]) == 0
    status = speicher.lies_json(konfig.GESCHICHTE / "status.json")
    assert status["preise"]["fertig"] is True
    assert status["stand"] == "2026-09-26"


def test_nur_offene_teile_und_komma_liste(ablage, monkeypatch):
    inhalt = pink_sheet()
    abrufe = []

    def bytes_holen(url, params=None, timeout=120):
        abrufe.append(url)
        return inhalt if url.endswith(".xlsx") else psd_zip()

    monkeypatch.setattr(netz, "hole_bytes", bytes_holen)
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: (_ for _ in ()).throw(AbrufFehler("aus")))
    assert geschichte.main(["--nur", "preise, ernte", "--heute", "2026-09-26"]) == 0
    status = speicher.lies_json(konfig.GESCHICHTE / "status.json")
    assert status["preise"]["fertig"] and status["ernte"]["fertig"]
    assert any("Ernte Indonesia" in m for m in status["meldungen"])
    anzahl = len(abrufe)
    assert geschichte.main(["--nur", "preise,ernte", "--nur-offene", "--heute", "2026-09-27"]) == 0
    assert len(abrufe) == anzahl                                    # alles fertig: kein Abruf
    assert speicher.lies_json(konfig.GESCHICHTE / "status.json")["stand"] == "2026-09-26"   # nichts geschrieben
    with pytest.raises(SystemExit):
        geschichte.main(["--nur", "kakao"])


def test_preise_werden_nicht_schlechter(ablage, monkeypatch):
    k = konfig.konfiguration()
    speicher.schreibe_json(konfig.GESCHICHTE / "preise.json", {
        "stand": "2026-09-20", "herkunft": {"palmoel": "Weltbank Pink Sheet"},
        "reihen": {"palmoel": [{"datum": "1960-01-01", "wert": 200.0}]}})
    monkeypatch.setattr(netz, "hole_bytes", lambda url, params=None, timeout=120: (_ for _ in ()).throw(AbrufFehler("404")))
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: (_ for _ in ()).throw(AbrufFehler("aus")))
    monkeypatch.setattr(kurse, "hole_fred", lambda url, serie: [{"datum": "1992-01-01", "wert": 1.0}])
    daten = geschichte.preise(k, melde=lambda t: None)
    assert daten["reihen"]["palmoel"][0]["datum"] == "1960-01-01"        # die längere Reihe bleibt
    assert daten["reihen"]["brent"][0]["datum"] == "1992-01-01"
    assert any("bleibt" in f for f in daten["fehler"])
