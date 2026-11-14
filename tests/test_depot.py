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
        # Seit 08.10.2026 kommen mit den neuen Formularen weitere Währungen dazu (GBP, CHF, THB).
        assert ticker.startswith("EUR") and ticker.endswith("=X")
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
    # Seit 08.10.2026 kommen weitere Zweige dazu (neue Länder, neue Agrarwerte) — die vier Alten müssen da sein.
    assert {"palmoel", "metall", "ersatz_haselnuss", "ersatz_palladium"} <= set(idx["zweige"])
    assert idx["werte"]["F34.SI"]["waehrung"] == "SGD" and idx["werte"]["F34.SI"]["archiv"] == "daten/preise/F34_SI.csv"
    assert idx["werte"]["LYC.AX"] == {**idx["werte"]["LYC.AX"], "waehrung": "AUD", "vergleich": "XME", "zweig": "metall"}
    assert idx["werte"]["SHV.AX"]["vergleich"] == "^AXJO" and idx["werte"]["PPLT"]["vergleich"] == "GLD"
    assert idx["zweige"]["metall"]["regel"]["kalendertage"] == 90 and idx["zweige"]["palmoel"]["regel"]["gruen"]
    assert idx["zweige"]["ersatz_palladium"]["quelle"]["pfad"] == "daten/ersatz/palladium/schattendepot.json"
    assert {"USD", "SGD"} <= set(idx["devisen"]) and "AUD" not in idx["devisen"]   # Australischer Dollar fehlte beim Abruf
    assert "werkzeuge/schattendepot.py" in idx["dateien"] and "daten/depot/kurse/EURUSD_X.csv" in idx["dateien"]
    assert "daten/metall/china/kurse/XME.csv" in idx["dateien"]
    assert e["zustand"] == "Warnung" and e["devisen_fehler"][0].startswith("EURAUD=X")
    assert e["probe"]["offen"]["anzahl"] == 1                 # der Palmöl-Kauf, ohne die Metall-Positionen
    status = (konfig.ABGABE / "status-depot.md").read_text(encoding="utf-8")
    assert "Zustand: Warnung" in status and "1 offene" in status


def test_regel2_grenze_unter_dem_hoechststand():
    """Regel 2 (A29): Höchststand seit Einstieg, Grenze 20 Prozent darunter, Frist der bisherigen Regel bleibt."""
    w = depot.werkzeug()
    reihe = [{"datum": f"2026-10-{t:02d}", "schluss": s} for t, s in [(2, 115), (5, 130), (6, 120), (7, 104), (8, 140)]]
    g = w.grenze(reihe, 100.0, 0.20)
    assert g["hoechststand"] == 140 and g["erreicht_am"] == {"datum": "2026-10-07", "kurs": 104}
    g = w.grenze(reihe[:3], 100.0, 0.20)                        # 130 hoch, heute 120: noch nicht erreicht
    assert g["erreicht_am"] is None and g["grenze"] == 104.0 and g["abstand"] == 0.1538
    g = w.grenze([{"datum": "2026-10-02", "schluss": 90}, {"datum": "2026-10-05", "schluss": 80}], 100.0, 0.20)
    assert g["hoechststand_datum"] is None and g["erreicht_am"]["kurs"] == 80   # nie über Einstieg: Grenze bei 80
    assert w.grenze([], 100.0, 0.20)["erreicht_am"] is None                    # ohne Kurse kein Schluss
    frist, text = w.frist("2026-09-22", {"kalendertage": 90, "lockerung": True, "mit_vorgabe": True, "nachlauf": 0.2})
    assert frist == "2026-12-21"
    assert w.mit_grenze(text, {"nachlauf": 0.2}).endswith("außerdem bei 20 Prozent unter dem Höchststand")


def test_regel2_hinweise(basis):
    """Metall-Zweig auf Regel 2: PPTA steigt von 20 auf 22 → kein Hinweis; fällt er unter 17,60, Grenze erreicht."""
    idx_pfad = basis / "daten/depot/index.json"
    idx = json.loads(idx_pfad.read_text(encoding="utf-8"))
    idx["zweige"]["metall"].update({"gilt": "regel2", "regel": {"kalendertage": 90, "lockerung": True,
                                                                "mit_vorgabe": True, "nachlauf": 0.2}})
    idx_pfad.write_text(json.dumps(idx), encoding="utf-8")
    e = depot.werkzeug().rechnen(basis, HEUTE, ZUSATZ[:1])
    ppta = _pos(e, "PPTA")
    assert ppta["regel"]["grenze"]["hoechststand"] == 22.0 and ppta["regel"]["grenze"]["erreicht_am"] is None
    arten = {(h["art"], h.get("ticker") or h["zweig"]) for h in e["regel_hinweise"]}
    assert ("regel_abweichend", "metall") not in arten and not any(a.startswith("grenze") for a, _ in arten)
    _archiv(basis / "daten/metall/china/kurse/PPTA.csv",
            _stufen("2026-09-01", "2026-10-02", {"2026-09-01": 18.0, "2026-09-22": 20.0, "2026-09-25": 22.0,
                                                 "2026-09-29": 18.0, "2026-10-01": 17.5}))
    e = depot.werkzeug().rechnen(basis, date(2026, 10, 2), ZUSATZ[:1])
    h = next(h for h in e["regel_hinweise"] if h["art"] == "grenze_erreicht")
    assert h["ticker"] == "PPTA" and h["datum"] == "2026-10-01" and h["kurs"] == 17.5
    e = depot.werkzeug().rechnen(basis, date(2026, 9, 30), ZUSATZ[:1])    # 18,00 liegt 2,3 % über 17,60
    assert any(h["art"] == "grenze_nah" and h["ticker"] == "PPTA" for h in e["regel_hinweise"])


# ------------------------------------------------------------------ Handspur (A135, A136; Fassung 1.2)
# Ausschnitt aus den echten Archiven daten/preise/COCO_L.csv und daten/depot/kurse/EURUSD_X.csv (Stand 14.11.2026),
# fest eingetragen, weil der tägliche Lauf die Archive neu schreibt.
COCO_AUSSCHNITT = {"2026-07-31": 8.7875, "2026-08-03": 9.57, "2026-08-04": 9.5775, "2026-08-05": 9.555,
                   "2026-08-06": 9.4462, "2026-08-07": 9.4225, "2026-08-10": 9.415, "2026-08-11": 9.04,
                   "2026-08-12": 9.15, "2026-08-13": 9.115, "2026-08-14": 9.235, "2026-08-17": 9.5463,
                   "2026-08-18": 9.4875, "2026-08-19": 9.6225, "2026-08-20": 9.7288, "2026-08-21": 9.665}
EURUSD_AUSSCHNITT = {"2026-07-31": 1.1524, "2026-08-03": 1.1544, "2026-08-04": 1.1507, "2026-08-05": 1.1532,
                     "2026-08-06": 1.1557, "2026-08-07": 1.1525, "2026-08-10": 1.1556, "2026-08-11": 1.1546,
                     "2026-08-12": 1.1544, "2026-08-13": 1.153, "2026-08-14": 1.1535, "2026-08-17": 1.1574,
                     "2026-08-18": 1.1583, "2026-08-19": 1.1579, "2026-08-20": 1.1674, "2026-08-21": 1.1688}
HAND_REGEL = {"name": "Handspur: 20 Prozent unter dem Höchststand, spätestens nach 180 Tagen",
              "kalendertage": 180, "nachlauf": 0.2}


def _hand_basis(tmp_path, eintraege, werte, archive, devisen=None):
    """Nur die Handspur: Index mit dem Zweig hand, den genannten Werten und Archiven."""
    b = tmp_path
    for pfad, reihe in {**archive, "daten/depot/kurse/EURUSD_X.csv": devisen or EURUSD_AUSSCHNITT}.items():
        _archiv(b / pfad, reihe)
    index = {"stand": "2026-11-14T23:00:00+01:00", "betrag": 1000, "basis": "EUR",
             "devisen": {"USD": "daten/depot/kurse/EURUSD_X.csv"}, "werte": werte, "vergleiche": {},
             "zweige": {"hand": {"name": "Handeingabe", "gilt": "bisher", "regel": HAND_REGEL,
                                 "regel_name": HAND_REGEL["name"],
                                 "quelle": {"art": "hand", "herkunft": "konfig/depot.yaml", "eintraege": eintraege}}},
             "dateien": ["daten/depot/index.json"]}
    (b / "daten/depot/index.json").write_text(json.dumps(index), encoding="utf-8")
    return b


def _usd(name, ticker):
    return {"name": name, "zweig": "kakao", "waehrung": "USD", "archiv": f"daten/preise/{ticker.replace('.', '_')}.csv",
            "vergleich": None}


def test_handspur_bekannter_fall(tmp_path):
    """Probe 1: Kauf am 03.08.2026 zum Schluss 9,57 USD bei 1,1544 USD je Euro, bewertet am 21.08.

    Von Hand: Menge 1000 × 1,1544 ÷ 9,57 = 120,626959; Wert 120,626959 × 9,665 ÷ 1,1688 = 997,48 Euro (−0,25 %,
    in Dollar +0,99 %); Höchststand seit Einstieg 9,7288 am 20.08., Grenze 0,8 × 9,7288 = 7,78304, Abstand
    9,665 ÷ 7,78304 − 1 = 24,18 %; Frist 03.08. + 180 Tage = 30.01.2027, am 21.08. noch 162 Tage.
    """
    b = _hand_basis(tmp_path, [{"ticker": "COCO.L", "seit": "2026-08-03", "anlass": "Probe", "ampel": "Kakao Gelb, Zahl 10"}],
                    {"COCO.L": _usd("WisdomTree Cocoa (ETC)", "COCO.L")}, {"daten/preise/COCO_L.csv": COCO_AUSSCHNITT})
    e = depot.werkzeug().rechnen(b, date(2026, 8, 21))
    p = _pos(e, "COCO.L")
    assert p["zweig"] == "hand" and p["offen"] and p["status"] == "ok" and p["waehrung"] == "USD"
    assert p["anlass"] == "Probe" and p["ampel"] == "Kakao Gelb, Zahl 10"
    assert p["einstieg"] == {"kurs": 9.57, "datum": "2026-08-03", "devisen": 1.1544}
    assert p["ende"] == {"kurs": 9.665, "datum": "2026-08-21", "devisen": 1.1688, "art": "heute"}
    assert p["menge"] == 120.626959 and p["wert_eur"] == 997.48
    assert p["veraenderung_eur"] == -0.0025 and p["veraenderung_lokal"] == 0.0099
    g = p["regel"]["grenze"]
    assert g["hoechststand"] == 9.7288 and g["hoechststand_datum"] == "2026-08-20"
    assert g["grenze"] == 7.78304 and g["abstand"] == 0.2418 and g["erreicht_am"] is None
    assert p["regel"]["frist"] == "2027-01-30" and p["regel"]["tage_bis_frist"] == 162
    assert p["regel"]["beschreibung"] == "nach 180 Tagen, außerdem bei 20 Prozent unter dem Höchststand"
    assert e["handspur"]["offen"] == {"anzahl": 1, "einsatz_eur": 1000.0, "wert_eur": 997.48,
                                      "veraenderung_eur": -0.0025, "ergebnis_eur": -2.52}
    assert e["handspur"]["wartet"] == 0 and e["gesamt"]["zusammen"]["anzahl"] == 0
    assert "hand" not in e["zweige"] and e["fehler"] == [] and e["regel_hinweise"] == []
    frueh = depot.werkzeug().rechnen(b, date(2026, 8, 7))
    assert [h["art"] for h in frueh["regel_hinweise"]] == ["neu_gekauft"]
    assert frueh["regel_hinweise"][0]["anlass"] == "Probe"


def test_handspur_schluss_von_selbst(tmp_path):
    """Probe 2: Grenze 20 Prozent unter dem Höchststand, Frist 180 Tage, am selben Tag zählt die Grenze.

    Kauf jeweils am Montag, 05.01.2026, zu 10 USD; Frist 05.01. + 180 = Samstag, 04.07.2026, also Schluss zum
    ersten Kurs danach, Montag, 06.07. Der Dollar steht fest bei 1,25 je Euro.
    """
    fx = _stufen("2026-01-01", "2026-12-31", {"2026-01-01": 1.25})
    grenze = _stufen("2026-01-05", "2026-03-31", {"2026-01-05": 10.0, "2026-01-12": 11.0, "2026-01-20": 12.5,
                                                  "2026-01-27": 10.4, "2026-02-02": 10.0, "2026-02-03": 9.0})
    seitwaerts = _stufen("2026-01-05", "2026-07-31", {"2026-01-05": 10.0, "2026-03-02": 10.4, "2026-05-04": 9.8})
    selber_tag = _stufen("2026-01-05", "2026-07-31", {"2026-01-05": 10.0, "2026-02-02": 11.0, "2026-07-06": 8.8,
                                                      "2026-07-07": 9.5})
    werte = {t: _usd(t, t) for t in ("GRZ.L", "FRS.L", "TAG.L")}
    b = _hand_basis(tmp_path, [{"ticker": t, "seit": "2026-01-05", "anlass": t, "ampel": None} for t in werte], werte,
                    {"daten/preise/GRZ_L.csv": grenze, "daten/preise/FRS_L.csv": seitwaerts,
                     "daten/preise/TAG_L.csv": selber_tag}, devisen=fx)
    e = depot.werkzeug().rechnen(b, date(2026, 7, 31))

    grz = _pos(e, "GRZ.L")              # Höchststand 12,50 am 20.01., Grenze 10,00, am 02.02. erreicht
    assert not grz["offen"] and grz["schluss"] == "2026-02-02" and grz["grund"] == "Grenze 20 Prozent unter dem Höchststand"
    assert grz["ende"] == {"kurs": 10.0, "datum": "2026-02-02", "devisen": 1.25, "art": "Schluss"}
    assert grz["wert_eur"] == 1000.0 and grz["hoechster"] == 0.25
    assert grz["regel"]["grenze"]["erreicht_am"] == {"datum": "2026-02-02", "kurs": 10.0}

    frs = _pos(e, "FRS.L")              # nie 20 Prozent unter 10,40: Schluss zur Frist am 06.07. zu 9,80
    assert not frs["offen"] and frs["schluss"] == "2026-07-06" and frs["grund"] == "Frist 180 Tage"
    assert frs["wert_eur"] == 980.0 and frs["tage"] == 182

    tag = _pos(e, "TAG.L")              # 8,80 am Fristtag liegt auf der Grenze unter 11,00: die Grenze zählt
    assert tag["schluss"] == "2026-07-06" and tag["grund"] == "Grenze 20 Prozent unter dem Höchststand"
    assert tag["wert_eur"] == 880.0

    assert e["handspur"]["geschlossen"]["anzahl"] == 3 and e["handspur"]["offen"]["anzahl"] == 0
    assert e["handspur"]["geschlossen"]["wert_eur"] == 2860.0
    assert e["regel_hinweise"] == []                                 # alle Schlüsse älter als eine Woche
    zwei_tage = depot.werkzeug().rechnen(b, date(2026, 7, 8))
    arten = {(h["art"], h["ticker"]) for h in zwei_tage["regel_hinweise"]}
    assert arten == {("neu_geschlossen", "FRS.L"), ("neu_geschlossen", "TAG.L")}   # GRZ schloss vor Monaten

    # Vor dem Schluss: offen, mit den Hinweisen grenze_nah und frist_bald, nie grenze_erreicht oder frist_erreicht
    vorher = depot.werkzeug().rechnen(b, date(2026, 1, 30))         # 10,40 liegt 4 Prozent über der Grenze 10,00
    assert _pos(vorher, "GRZ.L")["offen"] and _pos(vorher, "GRZ.L")["regel"]["grenze"]["abstand"] == 0.04
    assert ("grenze_nah", "GRZ.L") in {(x["art"], x["ticker"]) for x in vorher["regel_hinweise"]}
    vorher = depot.werkzeug().rechnen(b, date(2026, 6, 30))
    h = {(x["art"], x["ticker"]) for x in vorher["regel_hinweise"]}
    assert ("frist_bald", "FRS.L") in h and ("frist_bald", "TAG.L") in h
    am_samstag = depot.werkzeug().rechnen(b, date(2026, 7, 4))     # Frist erreicht, Schluss erst am Montag
    assert _pos(am_samstag, "FRS.L")["offen"]
    assert not any(x["art"] in ("frist_erreicht", "grenze_erreicht") for x in am_samstag["regel_hinweise"])
    knapp = depot.werkzeug().rechnen(b, date(2026, 2, 2))
    assert not _pos(knapp, "GRZ.L")["offen"]                         # am Tag der Grenze schon geschlossen
    assert ("neu_geschlossen", "GRZ.L") in {(x["art"], x["ticker"]) for x in knapp["regel_hinweise"]}


def test_handspur_kuenstliche_ausfaelle(tmp_path):
    """Probe 3: ausstehender Kauf, unbekannter Wert, Wert ohne Währung, fehlendes Kursarchiv, Eintrag ohne seit."""
    werte = {"COCO.L": _usd("WisdomTree Cocoa (ETC)", "COCO.L"),
             "OHNEW.L": {**_usd("ohne Währung", "OHNEW.L"), "waehrung": None},
             "OHNEA.L": _usd("ohne Archiv", "OHNEA.L")}
    eintraege = [{"ticker": "COCO.L", "seit": "2026-11-16", "anlass": "Kakao", "ampel": None},
                 {"ticker": "UNBEKANNT", "seit": "2026-08-03"},
                 {"ticker": "OHNEW.L", "seit": "2026-08-03"},
                 {"ticker": "OHNEA.L", "seit": "2026-08-03"},
                 {"ticker": "COCO.L", "anlass": "ohne Kauftag"},
                 {"ticker": "COCO.L", "seit": "16.11.2026"}]
    b = _hand_basis(tmp_path, eintraege, werte,
                    {"daten/preise/COCO_L.csv": COCO_AUSSCHNITT, "daten/preise/OHNEW_L.csv": COCO_AUSSCHNITT})
    e = depot.werkzeug().rechnen(b, date(2026, 11, 14))
    coco = _pos(e, "COCO.L")
    assert coco["status"] == "Kauf am 2026-11-16 steht noch aus" and coco["wartet"] and coco["offen"]
    assert _pos(e, "OHNEW.L")["status"] == "ohne Währung"
    assert _pos(e, "OHNEA.L")["status"] == "ohne Kursarchiv"
    assert e["handspur"]["wartet"] == 1 and e["handspur"]["offen"]["anzahl"] == 0
    assert "Wert UNBEKANNT fehlt im Index" in e["fehler"]
    assert "OHNEW.L: ohne Währung" in e["fehler"] and "OHNEA.L: ohne Kursarchiv" in e["fehler"]
    assert sum(f.startswith("Handeingabe ohne ticker oder gültiges seit") for f in e["fehler"]) == 2
    assert not any("steht noch aus" in f for f in e["fehler"])            # ein ausstehender Kauf ist kein Fehler
    arten = {(h["art"], h["ticker"]) for h in e["regel_hinweise"]}
    assert arten == {("nicht_bewertbar", "OHNEW.L"), ("nicht_bewertbar", "OHNEA.L")}
    # Kauftag schon vorbei, aber noch kein Kurs bis heute: steht ebenfalls noch aus
    b2 = _hand_basis(tmp_path / "b2", [{"ticker": "COCO.L", "seit": "2026-08-22"}],
                     {"COCO.L": _usd("WisdomTree Cocoa (ETC)", "COCO.L")}, {"daten/preise/COCO_L.csv": COCO_AUSSCHNITT})
    assert _pos(depot.werkzeug().rechnen(b2, date(2026, 8, 24)), "COCO.L")["status"] == "Kauf am 2026-08-22 steht noch aus"


def test_handspur_gegenprobe(basis):
    """Probe 4: Gesamtstand, Zweige, übrige Positionen, Hinweise und Fehler sind mit und ohne Handspur gleich."""
    ohne = depot.werkzeug().rechnen(basis, HEUTE, ZUSATZ)
    idx_pfad = basis / "daten/depot/index.json"
    idx = json.loads(idx_pfad.read_text(encoding="utf-8"))
    idx["werte"]["COCO.L"] = _usd("WisdomTree Cocoa (ETC)", "COCO.L")
    idx["zweige"]["hand"] = {"name": "Handeingabe", "gilt": "bisher", "regel": HAND_REGEL, "regel_name": HAND_REGEL["name"],
                             "quelle": {"art": "hand", "eintraege": [{"ticker": "COCO.L", "seit": "2026-08-03"}]}}
    idx_pfad.write_text(json.dumps(idx), encoding="utf-8")
    _archiv(basis / "daten/preise/COCO_L.csv", COCO_AUSSCHNITT)
    mit = depot.werkzeug().rechnen(basis, HEUTE, ZUSATZ)
    assert mit["gesamt"] == ohne["gesamt"] and mit["zweige"] == ohne["zweige"]
    assert [p for p in mit["positionen"] if p["zweig"] != "hand"] == ohne["positionen"]
    assert [h for h in mit["regel_hinweise"] if h["zweig"] != "hand"] == ohne["regel_hinweise"]
    assert mit["fehler"] == ohne["fehler"] and "handspur" not in ohne
    assert mit["handspur"]["offen"]["anzahl"] == 1 and _pos(mit, "COCO.L")["zweig"] == "hand"


def test_index_mit_handspur(ablage):
    """Der Index führt die Handspur aus dem Formular als Zweig hand; COCO.L rechnet in Dollar (A136, W1)."""
    d = konfig.lade_yaml(konfig.KONFIG / "depot.yaml")
    zeit = datetime(2026, 11, 14, 23, 0, tzinfo=konfig.ZEITZONE)
    idx = depot.index(d, {}, zeit)
    hand = idx["zweige"]["hand"]
    assert hand["quelle"]["art"] == "hand" and hand["gilt"] == "bisher"
    assert hand["regel"]["kalendertage"] == 180 and hand["regel"]["nachlauf"] == 0.2
    assert {"ticker": "COCO.L", "seit": "2026-11-16"}.items() <= hand["quelle"]["eintraege"][0].items()
    assert idx["werte"]["COCO.L"]["waehrung"] == "USD" and idx["werte"]["COCO.L"]["zweig"] == "kakao"
    # Ein Wert, den nur die Handspur führt: mit Name und Börse dabei, ohne Name nicht
    d2 = {**d, "handeingaben": {"regel": HAND_REGEL, "eintraege": [
        {"ticker": "NUR.N", "seit": date(2026, 11, 16), "name": "Nur Hand", "boerse": "NYSE"},
        {"ticker": "OHNE.N", "seit": "2026-11-16"}]}}
    idx = depot.index(d2, {}, zeit)
    assert idx["werte"]["NUR.N"] == {"name": "Nur Hand", "zweig": "hand", "waehrung": "USD",
                                     "archiv": "daten/preise/NUR_N.csv", "vergleich": None}
    assert "OHNE.N" not in idx["werte"] and idx["zweige"]["hand"]["quelle"]["eintraege"][0]["seit"] == "2026-11-16"
    assert "daten/preise/NUR_N.csv" in idx["dateien"]
    assert "hand" not in depot.index({k: v for k, v in d.items() if k != "handeingaben"}, {}, zeit)["zweige"]
