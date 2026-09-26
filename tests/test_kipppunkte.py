"""Kipppunkt-Register: Statistik, Leseroutinen, ein ganzer Lauf mit erfundenem Netz, Vorlesetext."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, timedelta
from urllib.parse import unquote

import pytest

from anlage import kipppunkte, konfig, netz, speicher
from anlage.ausgabe import kipppunkte_text, vorlesen

HEUTE = date(2026, 9, 26)


# ------------------------------------------------------------------ Statistik
def test_statistik():
    xs = [float(x) for x in range(10)]
    assert kipppunkte.steigung(xs, [2 * x + 1 for x in xs]) == pytest.approx(2.0)
    assert kipppunkte.rest_nach_trend(xs, [2 * x + 1 for x in xs]) == pytest.approx([0.0] * 10)
    wechselnd = [1.0, -1.0] * 10
    assert kipppunkte.ac1(wechselnd) == pytest.approx(-0.95, abs=0.01)
    glatt = [float(i // 5) for i in range(40)]
    assert kipppunkte.ac1(glatt) > 0.8
    jahre = {j: 0.02 * (j - 1990) for j in range(1990, 2026)}
    assert kipppunkte.trend_je_jahrzehnt(jahre, 1996, 2025) == pytest.approx(0.2)
    assert kipppunkte.traegheit({j: 1.0 for j in range(2000, 2010)}, 2000, 2009) is None   # zu kurz


def test_quartal():
    assert kipppunkte.quartal(date(2026, 9, 26)) == "2026-Q3"
    assert kipppunkte.quartal(date(2027, 1, 1)) == "2027-Q1"


# ------------------------------------------------------------------ Leseroutinen
def test_leseroutinen():
    erddap = ("time,depth,latitude,longitude,ssta\nUTC,m,degrees_north,degrees_east,degree_C\n"
              "2026-08-15T00:00:00Z,0.0,44.0,300.0,1.0\n2026-08-15T00:00:00Z,0.0,60.0,300.0,3.0\n"
              "2026-08-15T00:00:00Z,0.0,60.0,302.0,NaN\n")
    werte = kipppunkte.lies_erddap(erddap)
    assert list(werte) == ["2026-08"] and 1.0 < werte["2026-08"] < 2.0          # nach Breite gewichtet
    caag = "# Title\n# Units\nDate,Departure from Average\n185001,-0.07\n202608,1.08\n"
    assert kipppunkte.lies_caag(caag) == {"1850-01": -0.07, "2026-08": 1.08}
    amoc = "# Bitte zitieren\nYear,Month,RAPID (Sv),RAPID uncertainty\n2004,4,17.64,\n2004,5,16.36,\n"
    assert kipppunkte.lies_amoc(amoc) == {"2004-04": 17.64, "2004-05": 16.36}
    nrcs = [{"data": [{"values": [{"value": 10.0, "median": 20.0}]}]},
            {"data": [{"values": [{"value": 5.0, "median": None}]}]}]
    assert kipppunkte.lies_nrcs(nrcs) == {"summe": 10.0, "median": 20.0, "n": 1}
    assert kipppunkte.zaehle_braende(_zip(3, 2), "Amazônia") == 3


def test_rapid_netcdf():
    netCDF4 = pytest.importorskip("netCDF4")
    nc = netCDF4.Dataset("probe.nc", "w", memory=2000)
    nc.createDimension("time", None)
    zeit = nc.createVariable("time", "f8", ("time",))
    zeit.units = "days since 2004-4-1 00:00:00"
    moc = nc.createVariable("moc_mar_hc10", "f8", ("time",), fill_value=-99999.0)
    tage = [i / 2 for i in range(0, 2 * 61)]                     # April und Mai 2004, zweimal täglich
    zeit[:] = tage
    werte = [17.0 if t < 30 else 15.0 for t in tage]
    werte[0] = -99999.0                                           # Fehlwert
    moc[:] = werte
    inhalt = bytes(nc.close())
    monate = kipppunkte.lies_rapid_nc(inhalt)
    assert monate == {"2004-04": 17.0, "2004-05": 15.0}


# ------------------------------------------------------------------ Erfundenes Netz
def _zip(amazonas: int, cerrado: int) -> bytes:
    puffer = io.BytesIO()
    zeilen = ["id_bdq,foco_id,lat,lon,data_pas,pais,estado,municipio,bioma"]
    zeilen += [f"{i},x,-5,-60,2024-01-02 17:04:00,Brasil,PARÁ,ALTAMIRA,Amazônia" for i in range(amazonas)]
    zeilen += [f"{i},x,-15,-47,2024-01-02 17:04:00,Brasil,GOIÁS,FORMOSA,Cerrado" for i in range(cerrado)]
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("focos.csv", "\n".join(zeilen) + "\n")
    return puffer.getvalue()


def _kaltfleck_wert(jahr: int) -> float:
    """Box wird ab 1990 gegenüber der Welt kühler; davor ruhig."""
    return 0.2 - (0.02 * (jahr - 1990) if jahr > 1990 else 0.0)


class Netz:
    def __init__(self):
        self.abrufe: list[str] = []

    def hole_text(self, url, params=None, kopf=None):
        self.abrufe.append(url)
        if "erddap" in url:
            t = re.search(r"ssta\[\((\d{4})-\d\d-\d\d\):1:\(([^)]+)\)", unquote(url))
            von = int(t.group(1))
            bis, bis_monat = (2026, 8) if t.group(2) == "last" else (int(t.group(2)[:4]), int(t.group(2)[5:7]))
            if t.group(2) != "last":
                assert (bis, bis_monat) <= (2026, 8), "Ende hinter dem letzten Wert"
            zeilen = ["time,depth,latitude,longitude,ssta", "UTC,m,degrees_north,degrees_east,degree_C"]
            for j in range(von, bis + 1):
                for m in range(1, 13):
                    if (j, m) > (bis, min(bis_monat, 8) if bis == HEUTE.year else bis_monat):
                        break
                    welt = 0.01 * (j - 1900)
                    zeilen.append(f"{j}-{m:02d}-15T00:00:00Z,0.0,50.0,320.0,{welt + _kaltfleck_wert(j):.4f}")
            return "\n".join(zeilen) + "\n"
        if "climate-at-a-glance" in url:
            zeilen = ["# Titel", "Date,Departure from Average"]
            zeilen += [f"{j}{m:02d},{0.01 * (j - 1900):.3f}" for j in range(1850, 2027) for m in range(1, 13)
                       if (j, m) <= (2026, 8)]
            return "\n".join(zeilen) + "\n"
        if "amoc_rapid" in url:
            zeilen = ["Year,Month,RAPID (Sv),RAPID uncertainty"]
            zeilen += [f"{j},{m},{18.0 - 0.1 * (j - 2004):.2f}," for j in range(2004, 2023) for m in range(1, 13)
                       if (j, m) >= (2004, 4)]
            return "\n".join(zeilen) + "\n"
        raise netz.AbrufFehler(f"unbekannt: {url}")

    def hole_bytes(self, url, params=None, timeout=120):
        self.abrufe.append(url)
        if "moc_transports.nc" in url:
            raise netz.AbrufFehler("RAPID nicht erreichbar")        # Rückfall auf die Monatsreihe des Met Office
        if "queimadas" in url:
            jahr = int(re.search(r"_(\d{4})\.zip", url).group(1))
            return _zip(100 if jahr < 2023 else 150, 10)
        raise netz.AbrufFehler(url)

    def hole_json(self, url, params=None, kopf=None):
        self.abrufe.append(url)
        if url.endswith("/stations"):
            return [{"stationTriplet": "301:CA:SNTL"}, {"stationTriplet": "356:CA:SNTL"}]
        if url.endswith("/data"):
            jahr = int(params["beginDate"][:4])
            anteil = 0.4 if jahr in (2015, 2021, 2022) else 1.0
            return [{"data": [{"values": [{"value": 20.0 * anteil, "median": 20.0}]}]},
                    {"data": [{"values": [{"value": 10.0 * anteil, "median": 10.0}]}]}]
        if "archive" in url:
            von, bis = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
            tage = [von + timedelta(days=i) for i in range((bis - von).days + 1)]
            erwaermung = [0.03 * (d.year - 1981) for d in tage]
            return {"daily": {
                "time": [d.isoformat() for d in tage],
                "temperature_2m_max": [24.0 + (8 if d.month in (6, 7, 8) else 0) + e for d, e in zip(tage, erwaermung)],
                "temperature_2m_min": [10.0 + e for e in erwaermung],
                "temperature_2m_mean": [(6.0 if d.month in (11, 12, 1, 2) else 16.0) + e for d, e in zip(tage, erwaermung)],
                "precipitation_sum": [1.5 for _ in tage]}}
        raise netz.AbrufFehler(f"unbekannt: {url}")


def _oni(ablage_pfad):
    """ONI mit drei El Niños: 1972 (stark), 1997 (sehr stark), 2015 (sehr stark)."""
    reihe = []
    for j in range(1950, 2027):
        for m in range(1, 13):
            if (j, m) > (2026, 7):
                break
            wert = 0.0
            for jahr, hoch in ((1972, 1.8), (1997, 2.4), (2015, 2.6)):
                if (jahr, 5) <= (j, m) <= (jahr + 1, 2):
                    wert = hoch
            reihe.append({"jahreszeit": "JJA", "jahr": j, "monat": m, "wert": wert})
    speicher.schreibe_json(konfig.KLIMA / "oni.json", {"reihe": reihe})


@pytest.fixture
def register(ablage, monkeypatch):
    falsch = Netz()
    monkeypatch.setattr(netz, "hole_text", falsch.hole_text)
    monkeypatch.setattr(netz, "hole_json", falsch.hole_json)
    monkeypatch.setattr(netz, "hole_bytes", falsch.hole_bytes)
    _oni(ablage)
    return falsch


def test_lauf_mit_erfundenem_netz(register):
    assert kipppunkte.main(["--heute", HEUTE.isoformat(), "--pro-minute", "0"]) == 0
    b = speicher.lies_json(konfig.DATEN / "kipppunkte.json")
    ind = b["indikatoren"]
    assert b["quartal"] == "2026-Q3" and b["vollstaendig"], {n: e.get("meldung") for n, e in ind.items()}

    kf = ind["kaltfleck"]
    assert kf["bis_jahr"] == 2025 and kf["schere_letzte_5"] < -0.5 and kf["trend_30"] == pytest.approx(-0.2, abs=0.01)
    assert ind["amoc"]["quelle"] == "Met Office" and ind["amoc"]["trend_je_jahrzehnt"] == pytest.approx(-1.0, abs=0.05)
    en = ind["el_nino"]
    assert [f["sehr_stark"] for f in en["fenster"]] == [0, 1, 2] and en["staerkste"][0]["jahr"] in (2015, 2016)
    si = ind["sierra_schnee"]
    assert si["letztes_jahr"] == 2026 and si["arme_jahre_10"] == 2 and si["arme_jahre_davor"] == 1
    am = ind["amazonas_braende"]
    assert am["letztes_jahr"] == 2025 and am["letzte_zahl"] == 150 and am["mittel_vergleich"] == 100
    pk = ind["punkte"]["punkte"]
    assert set(pk) == {"jaen", "sul_de_minas", "giresun", "central_valley"}
    assert pk["sul_de_minas"]["masse"]["jahres_tmittel"]["trend_30"] == pytest.approx(0.3, abs=0.01)
    assert pk["jaen"]["masse"]["jahresregen"]["letzter_wert"] == pytest.approx(547.5, abs=2)

    # Vorlesetext: Zahlen ausgeschrieben, Grenze eingehalten, Schluss mit dem Hinweis
    teile = sorted(konfig.ABGABE.glob("kipppunkte-teil-*.md"))
    assert teile
    gesamt = ""
    for teil in teile:
        text = teil.read_text(encoding="utf-8")
        assert len(text) <= vorlesen.GRENZE
        rumpf = text.split("\n", 2)[2]
        assert not re.search(r"\d", rumpf), rumpf
        gesamt += rumpf
    assert "dritte Quartal zweitausendsechsundzwanzig" in gesamt
    assert "kühler als in der Vergleichszeit neunzehnhunderteinundfünfzig bis neunzehnhundertachtzig" in gesamt
    assert "je Jahrzehnt kühler" in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    status = (konfig.ABGABE / "status-kipppunkte.md").read_text(encoding="utf-8")
    assert "Zustand: in Ordnung" in status and "Quartal: 2026-Q3" in status

    # Zweiter Lauf im selben Quartal: nichts zu tun, kein Abruf
    register.abrufe.clear()
    assert kipppunkte.main(["--heute", (HEUTE + timedelta(days=1)).isoformat(), "--pro-minute", "0"]) == 0
    assert register.abrufe == []
    # Neues Quartal: holt nur, was fehlt (Queimadas und Sierra sind vollständig)
    assert kipppunkte.main(["--heute", "2026-10-01", "--pro-minute", "0"]) == 0
    assert not any("queimadas" in u for u in register.abrufe)
    assert speicher.lies_json(konfig.DATEN / "kipppunkte.json")["quartal"] == "2026-Q4"


def test_fehlende_quelle_wird_begrenzt_wiederholt(register, monkeypatch):
    def kaputt(url, params=None, timeout=120):
        raise netz.AbrufFehler("INPE nicht erreichbar")
    monkeypatch.setattr(netz, "hole_bytes", kaputt)
    tag = HEUTE
    for versuch in range(1, kipppunkte.MAX_VERSUCHE + 1):
        assert kipppunkte.main(["--heute", tag.isoformat(), "--pro-minute", "0"]) == 0
        lauf = speicher.lies_json(kipppunkte.ordner() / "lauf.json")
        assert lauf["versuche"] == versuch
        tag += timedelta(days=1)
    assert lauf["offen"] is False                                    # nach fünf Versuchen Ruhe bis zum nächsten Quartal
    b = speicher.lies_json(konfig.DATEN / "kipppunkte.json")
    assert b["indikatoren"]["amazonas_braende"]["status"] == "Fehler"
    text = " ".join(p.read_text(encoding="utf-8") for p in konfig.ABGABE.glob("kipppunkte-teil-*.md"))
    assert "Brandherde im Amazonasgebiet: Diesmal fehlen die Daten" in text
    assert "Zustand: Warnung" in (konfig.ABGABE / "status-kipppunkte.md").read_text(encoding="utf-8")


def test_zusammenfassung_ist_json_frei():
    bericht = {"stand": "2026-09-26T08:00:00+02:00", "quartal": "2026-Q3", "vollstaendig": False,
               "indikatoren": {"amoc": {"status": "Fehler", "meldung": "AbrufFehler: x"}}}
    text = kipppunkte_text.zusammenfassung(bericht)
    assert "amoc: Fehler" in text
    assert kipppunkte_text.zustand(bericht) == "Fehler"
    assert json.dumps(kipppunkte_text.absaetze(bericht))


def test_knappes_budget_meldet_ladende_reihen(register):
    assert kipppunkte.main(["--heute", HEUTE.isoformat(), "--pro-minute", "1000", "--budget-minuten", "0.001"]) == 0
    b = speicher.lies_json(konfig.DATEN / "kipppunkte.json")
    assert not b["vollstaendig"] and b["indikatoren"]["punkte"]["status"] == "unvollständig"
    assert b["indikatoren"]["punkte"]["punkte"]["jaen"]["vollstaendig"] is False
    text = " ".join(p.read_text(encoding="utf-8") for p in konfig.ABGABE.glob("kipppunkte-teil-*.md"))
    assert "Jaén in Andalusien" in text and "Die Reihe wird noch geladen" in text
    assert "Noch nicht alle Reihen sind gesammelt" in text
    lauf = speicher.lies_json(kipppunkte.ordner() / "lauf.json")
    assert lauf["offen"] is True                                        # am nächsten Tag geht es weiter
