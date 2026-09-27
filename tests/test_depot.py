"""Gesamt-Schattendepot: Werkzeug (Rechnung in Euro, Devisen, Vergleich, Fristen, Zusatz aus der Cloud)
und Vorbereitung auf GitHub (Devisenarchive, Index, Probe).

Erfunden: Palmöl kaufte am 1. Juni gedacht und schloss am 3. August, der Haselnuss-Sensor kaufte am
10. September Select Harvests, der Metall-Wächter am 22. September Perpetua. Heute ist der 27. September.
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from anlage import depot, konfig

HEUTE = date(2026, 9, 27)


def _archiv(pfad: Path, werte: dict[str, float]):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datum", "schluss", "volumen"])
        for d in sorted(werte):
            w.writerow([d, werte[d], 1000])


def _werktage(von: str, bis: str) -> list[str]:
    tage, d = [], date.fromisoformat(von)
    while d <= date.fromisoformat(bis):
        if d.weekday() < 5:
            tage.append(d.isoformat())
        d += timedelta(days=1)
    return tage


def _stufen(von: str, bis: str, wechsel: dict[str, float]) -> dict[str, float]:
    """Werktage mit einem Kurs, der sich an den genannten Tagen ändert."""
    werte, stand = {}, None
    for t in _werktage(von, bis):
        if t in wechsel:
            stand = wechsel[t]
        werte[t] = stand
    return {t: w for t, w in werte.items() if w is not None}


@pytest.fixture
def basis(tmp_path):
    b = tmp_path
    _archiv(b / "daten/depot/kurse/EURSGD_X.csv", _stufen("2026-05-01", "2026-09-25", {"2026-05-01": 1.5, "2026-07-01": 1.6}))
    _archiv(b / "daten/depot/kurse/EURAUD_X.csv", _stufen("2026-05-01", "2026-09-25", {"2026-05-01": 1.6, "2026-09-16": 1.65}))
    _archiv(b / "daten/depot/kurse/EURUSD_X.csv", _stufen("2026-05-01", "2026-09-25", {"2026-05-01": 1.1}))
    _archiv(b / "daten/preise/F34_SI.csv", _stufen("2026-05-01", "2026-09-25", {"2026-05-01": 3.0, "2026-07-15": 3.9, "2026-08-03": 3.6, "2026-09-01": 3.3}))
    _archiv(b / "daten/ersatz/haselnuss/kurse/SHV_AX.csv", _stufen("2026-09-01", "2026-09-25", {"2026-09-01": 4.0, "2026-09-25": 4.4}))
    _archiv(b / "daten/ersatz/haselnuss/kurse/_AXJO.csv", _stufen("2026-09-01", "2026-09-25", {"2026-09-01": 8000, "2026-09-25": 8200}))
    _archiv(b / "daten/metall/china/kurse/PPTA.csv", _stufen("2026-09-01", "2026-09-25", {"2026-09-01": 18.0, "2026-09-22": 20.0, "2026-09-25": 22.0}))
    _archiv(b / "daten/metall/china/kurse/XME.csv", _stufen("2026-09-01", "2026-09-25", {"2026-09-01": 100.0, "2026-09-25": 105.0}))
    logbuch = [
        {"zeit": "2026-05-20T04:36:00+02:00", "rohstoff": "palmoel", "farbe": "Gelb", "schattenkauf": False,
         "schattenschluss": False, "kurse": {"F34.SI": {"kurs": 3.0, "datum": "2026-05-19"}}},
        {"zeit": "2026-06-01T04:36:00+02:00", "rohstoff": "palmoel", "farbe": "Rot", "zahl": 7, "schattenkauf": True,
         "schattenschluss": False, "kurse": {"F34.SI": {"kurs": 3.0, "datum": "2026-06-01"},
                                             "E5H.SI": {"kurs": 0.3, "datum": "2026-06-01"}}},
        {"zeit": "2026-08-03T04:36:00+02:00", "rohstoff": "palmoel", "farbe": "Grün", "schattenkauf": False,
         "schattenschluss": True, "kurse": {"F34.SI": {"kurs": 3.6, "datum": "2026-07-31"},
                                            "E5H.SI": {"kurs": 0.27, "datum": "2026-07-31"}}},
    ]
    (b / "daten").mkdir(parents=True, exist_ok=True)
    (b / "daten/signale.jsonl").write_text("\n".join(json.dumps(e) for e in logbuch) + "\n", encoding="utf-8")
    (b / "daten/ersatz/haselnuss/schattendepot.json").write_text(json.dumps({"positionen": [
        {"zeit": "2026-09-10T04:07:00+02:00", "kurse": {"SHV.AX": {"kurs": 4.0, "datum": "2026-09-10"}},
         "vergleich": {"^AXJO": {"kurs": 8000, "datum": "2026-09-10"}}, "grund": "Rot"}]}), encoding="utf-8")
    index = {
        "stand": "2026-09-27T05:07:00+02:00", "betrag": 1000, "basis": "EUR",
        "devisen": {"SGD": "daten/depot/kurse/EURSGD_X.csv", "AUD": "daten/depot/kurse/EURAUD_X.csv",
                    "USD": "daten/depot/kurse/EURUSD_X.csv"},
        "werte": {
            "F34.SI": {"name": "Wilmar International", "zweig": "palmoel", "waehrung": "SGD", "archiv": "daten/preise/F34_SI.csv", "vergleich": None},
            "E5H.SI": {"name": "Golden Agri-Resources", "zweig": "palmoel", "waehrung": "SGD", "archiv": "daten/preise/E5H_SI.csv", "vergleich": None},
            "SHV.AX": {"name": "Select Harvests", "zweig": "ersatz_haselnuss", "waehrung": "AUD",
                       "archiv": "daten/ersatz/haselnuss/kurse/SHV_AX.csv", "vergleich": "^AXJO"},
            "PPTA": {"name": "Perpetua Resources", "zweig": "metall", "waehrung": "USD", "achse": "chip",
                     "archiv": "daten/metall/china/kurse/PPTA.csv", "vergleich": "XME"},
        },
        "vergleiche": {"^AXJO": {"name": "ASX 200", "archiv": "daten/ersatz/haselnuss/kurse/_AXJO.csv"},
                       "XME": {"name": "XME", "archiv": "daten/metall/china/kurse/XME.csv"}},
        "zweige": {
            "palmoel": {"name": "Palmöl", "quelle": {"art": "logbuch", "pfad": "daten/signale.jsonl", "rohstoff": "palmoel"},
                        "gilt": "bisher", "regel": {"gruen": True}, "regel_name": "bis Grün"},
            "metall": {"name": "Metall China", "quelle": {"art": "zusatz"}, "gilt": "bisher",
                       "regel": {"kalendertage": 90, "lockerung": True}, "regel_name": "Lockerung oder 90 Tage"},
            "ersatz_haselnuss": {"name": "Ersatz Haselnuss", "quelle": {"art": "ersatz", "pfad": "daten/ersatz/haselnuss/schattendepot.json"},
                                 "gilt": "bisher", "regel": {"bis_monat_tag": "09-30"}, "regel_name": "bis Ende der Ernte"},
            "ersatz_palladium": {"name": "Ersatz Palladium", "quelle": {"art": "ersatz", "pfad": "daten/ersatz/palladium/schattendepot.json"},
                                 "gilt": "zeit", "regel": {"halten": 120}, "regel_name": "nach 120 Handelstagen"},
        },
        "dateien": ["daten/depot/index.json"],
    }
    (b / "daten/depot/index.json").write_text(json.dumps(index), encoding="utf-8")
    return b


ZUSATZ = [{"zweig": "metall", "ticker": "PPTA", "seit": "2026-09-22", "anlass": "M1 Chip-Achse"},
          {"zweig": "metall", "ticker": "XYZ", "seit": "2026-09-22"}]


def _pos(e, ticker, offen=None):
    return next(p for p in e["positionen"] if p["ticker"] == ticker and (offen is None or p["offen"] == offen))


def test_rechnung_in_euro_mit_devisen_und_vergleich(basis):
    e = depot.werkzeug().rechnen(basis, HEUTE, ZUSATZ)

    wilmar = _pos(e, "F34.SI")          # 500 Aktien zu 3,00 SGD bei 1,5 SGD je Euro; Schluss 3,60 bei 1,6
    assert not wilmar["offen"] and wilmar["schluss"] == "2026-08-03" and wilmar["grund"] == "Rückkehr auf Grün"
    assert wilmar["menge"] == 500 and wilmar["wert_eur"] == 1125.0
    assert wilmar["veraenderung_eur"] == 0.125 and wilmar["veraenderung_lokal"] == 0.2
    assert wilmar["hoechster"] == 0.3                       # zwischendurch 3,90
    golden = _pos(e, "E5H.SI")          # ohne Archiv: Einstieg und Schluss aus dem Logbuch
    assert golden["wert_eur"] == 843.75 and golden["veraenderung_eur"] == -0.1562

    shv = _pos(e, "SHV.AX")             # 400 Aktien zu 4,00 AUD bei 1,6; heute 4,40 bei 1,65
    assert shv["offen"] and shv["wert_eur"] == 1066.67 and shv["veraenderung_lokal"] == 0.1
    assert shv["vergleich"]["veraenderung"] == 0.025 and shv["vergleich"]["vorsprung"] == 0.075
    assert shv["regel"]["frist"] == "2026-09-30" and shv["regel"]["tage_bis_frist"] == 3

    ppta = _pos(e, "PPTA")              # Einstieg aus dem Archiv am Kauftag, 20 USD; heute 22
    assert ppta["einstieg"] == {"kurs": 20.0, "datum": "2026-09-22", "devisen": 1.1}
    assert ppta["wert_eur"] == 1100.0 and ppta["vergleich"]["vorsprung"] == 0.05 and ppta["achse"] == "chip"
    assert ppta["regel"]["frist"] == "2026-12-21" and "Lockerung" in ppta["regel"]["beschreibung"]

    g = e["gesamt"]
    assert g["offen"] == {"anzahl": 2, "einsatz_eur": 2000.0, "wert_eur": 2166.67, "veraenderung_eur": 0.0833,
                          "ergebnis_eur": 166.67}
    assert g["geschlossen"]["wert_eur"] == 1968.75 and g["zusammen"]["anzahl"] == 4
    assert e["zweige"]["palmoel"]["geschlossen"]["anzahl"] == 2 and e["zweige"]["metall"]["offen"]["anzahl"] == 1
    assert [p["ticker"] for p in e["positionen"]][:2] == ["SHV.AX", "PPTA"] or e["positionen"][0]["offen"]
    assert "Zusatz mit unbekanntem Wert XYZ" in e["fehler"]
    assert e["hinweis"].endswith("Denkhilfe, keine Anlageberatung.")


def test_regel_hinweise(basis):
    e = depot.werkzeug().rechnen(basis, HEUTE, ZUSATZ[:1])
    arten = {(h["art"], h.get("ticker") or h["zweig"]) for h in e["regel_hinweise"]}
    assert ("frist_bald", "SHV.AX") in arten                 # Ende der Ernte in drei Tagen
    assert ("neu_gekauft", "PPTA") in arten                  # vor fünf Tagen
    assert ("regel_abweichend", "ersatz_palladium") in arten
    assert not any(a == "neu_geschlossen" for a, _ in arten)  # Palmöl schloss vor Wochen
    spaeter = depot.werkzeug().rechnen(basis, date(2026, 10, 2), ZUSATZ[:1])
    arten = {(h["art"], h.get("ticker")) for h in spaeter["regel_hinweise"]}
    assert ("frist_erreicht", "SHV.AX") in arten              # Schluss steht beim Sensor noch aus
    assert ("kurs_alt", "PPTA") in arten                      # letzter Kurs vom 25.


def test_404_antworten_stoeren_nicht(basis):
    """In der Cloud kann curl eine fehlende Datei als Text „404: Not Found“ speichern."""
    (basis / "daten/ersatz/palladium/kurse").mkdir(parents=True, exist_ok=True)
    (basis / "daten/ersatz/palladium/schattendepot.json").write_text("404: Not Found", encoding="utf-8")
    (basis / "daten/preise/E5H_SI.csv").write_text("404: Not Found", encoding="utf-8")
    e = depot.werkzeug().rechnen(basis, HEUTE, ZUSATZ[:1])
    assert e["gesamt"]["zusammen"]["anzahl"] == 4 and _pos(e, "E5H.SI")["wert_eur"] == 843.75


def test_kommandozeile(basis, capsys):
    w = depot.werkzeug()
    (basis / "metall.json").write_text(json.dumps(ZUSATZ[:1]), encoding="utf-8")
    assert w.main(["dateien", "--index", str(basis / "daten/depot/index.json")]) == 0
    assert capsys.readouterr().out.strip() == "daten/depot/index.json"
    assert w.main(["rechnen", "--basis", str(basis), "--heute", "2026-09-27", "--zusatz", str(basis / "metall.json"),
                   "--aus", str(basis / "depot.json")]) == 0
    e = json.loads((basis / "depot.json").read_text(encoding="utf-8"))
    assert e["gesamt"]["offen"]["anzahl"] == 2 and e["stand"] == "2026-09-27"


def test_vorbereitung_auf_github(ablage):
    """Index aus den echten Formularen, Devisenarchive aus erfundenen Kursen, Probe mit einem Palmöl-Kauf."""
    def holen(ticker, zeitraum):
        assert ticker in ("EURUSD=X", "EURSGD=X", "EURAUD=X")
        if ticker == "EURAUD=X":
            raise RuntimeError("Yahoo antwortet nicht")
        return [{"datum": d, "schluss": 1.1 if ticker == "EURUSD=X" else 1.5, "volumen": None}
                for d in _werktage("2026-09-01", "2026-09-25")]

    (konfig.DATEN).mkdir(parents=True, exist_ok=True)
    (konfig.DATEN / "signale.jsonl").write_text(json.dumps(
        {"zeit": "2026-09-21T04:36:00+02:00", "rohstoff": "palmoel", "farbe": "Rot", "zahl": 6, "schattenkauf": True,
         "schattenschluss": False, "kurse": {"F34.SI": {"kurs": 3.6, "datum": "2026-09-19"}}}) + "\n", encoding="utf-8")
    zeit = datetime(2026, 9, 27, 5, 7, tzinfo=konfig.ZEITZONE)
    e = depot.lauf(zeit, holen=holen)

    idx = json.loads((konfig.DATEN / "depot/index.json").read_text(encoding="utf-8"))
    assert set(idx["zweige"]) == {"palmoel", "metall", "ersatz_haselnuss", "ersatz_palladium"}
    assert idx["werte"]["F34.SI"]["waehrung"] == "SGD" and idx["werte"]["F34.SI"]["archiv"] == "daten/preise/F34_SI.csv"
    assert idx["werte"]["LYC.AX"] == {**idx["werte"]["LYC.AX"], "waehrung": "AUD", "vergleich": "XME", "zweig": "metall"}
    assert idx["werte"]["SHV.AX"]["vergleich"] == "^AXJO" and idx["werte"]["PPLT"]["vergleich"] == "GLD"
    assert idx["zweige"]["metall"]["regel"]["kalendertage"] == 90 and idx["zweige"]["palmoel"]["regel"]["gruen"]
    assert idx["zweige"]["ersatz_palladium"]["quelle"]["pfad"] == "daten/ersatz/palladium/schattendepot.json"
    assert set(idx["devisen"]) == {"USD", "SGD"}              # Australischer Dollar fehlte beim Abruf
    assert "werkzeuge/schattendepot.py" in idx["dateien"] and "daten/depot/kurse/EURUSD_X.csv" in idx["dateien"]
    assert "daten/metall/china/kurse/XME.csv" in idx["dateien"]
    assert e["zustand"] == "Warnung" and e["devisen_fehler"][0].startswith("EURAUD=X")
    assert e["probe"]["offen"]["anzahl"] == 1                 # der Palmöl-Kauf, ohne die Metall-Positionen
    status = (konfig.ABGABE / "status-depot.md").read_text(encoding="utf-8")
    assert "Zustand: Warnung" in status and "1 offene" in status
