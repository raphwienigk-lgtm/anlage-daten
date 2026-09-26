"""Ausstiegsregeln: Regelbausteine, Vergleich und ein ganzer Lauf mit erfundenen Kursen.

Erfunden: Die Antimon-Werte springen fünf Handelstage nach jeder Verschärfung auf der Chip-Achse um
35 Prozent und fallen nach dreißig Handelstagen zurück. Die Magnet-Werte bleiben flach. Select Harvests
springt eine Woche nach jedem Frostjahr um 25 Prozent und bleibt oben. Palmöl steigt nach dem Signal im
September 1997 binnen sechs Monaten um 40 Prozent und fällt bis Januar 1999 zurück.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from anlage import ausstieg, bilanz, konfig, speicher
from anlage.ausgabe import ausstieg_text, vorlesen
from anlage.quellen import kurse


# ------------------------------------------------------------------ Bausteine
def test_regelbausteine():
    reihe = [100, 110, 125, 131, 120, 100]
    assert ausstieg.schliessen(reihe, {"ziel": 0.30}) == {"offen": False, "schritt": 3, "grund": "Gewinnziel", "rendite": 0.31}
    e = ausstieg.schliessen(reihe, {"nachlauf": 0.20})
    assert (e["schritt"], e["grund"], e["rendite"]) == (5, "nachgezogene Grenze", 0.0)
    e = ausstieg.schliessen([100, 90, 79], {"verlust": 0.20})
    assert (e["schritt"], e["grund"]) == (2, "Verlustgrenze")
    e = ausstieg.schliessen([100, 105, 95, 96], {"nachlauf": 0.05, "nachlauf_ab": 0.10, "halten": 3})
    assert (e["schritt"], e["grund"]) == (3, "Haltedauer")            # Grenze noch nicht scharf
    e = ausstieg.schliessen(reihe, {}, vorgabe=2, vorgabe_grund="Lockerung")
    assert (e["schritt"], e["grund"], e["rendite"]) == (2, "Lockerung", 0.25)
    assert ausstieg.schliessen([100, 101], {"halten": 5})["offen"] is True
    assert ausstieg.gipfel(reihe, 4) == 0.31


def test_vergleich_nur_gemeinsame_faelle():
    zweig = {"bisher": {"name": "bisher"}, "varianten": [{"kennung": "zeit", "name": "zeit", "halten": 2},
                                                        {"kennung": "ziel", "name": "ziel", "ziel": 0.2, "halten": 4}]}
    faelle = [
        {"name": "A", "datum": "2020-01-02", "werte": [10, 11, 13, 12, 12], "ref": [5, 5, 5, 5, 5], "vorgabe": 4},
        {"name": "B", "datum": "2021-01-04", "werte": [10, 9, 9], "ref": [5, 5, 5], "vorgabe": None},   # bisher offen
    ]
    z = ausstieg.vergleiche(faelle, zweig)
    assert (z["faelle_gesamt"], z["verglichen"], z["offen"]) == (2, 1, 1)
    werte = {v["kennung"]: v for v in z["varianten"]}
    assert werte["ziel"]["mittel"] == 0.3 and werte["ziel"]["dauer"] == 2 and werte["zeit"]["mittel"] == 0.3
    assert werte["bisher"]["mittel"] == 0.2 and werte["bisher"]["vorsprung"] == 0.2
    assert z["massstab"] == "vorsprung" and z["vorn"] is None and z["vorn_gleichauf"] == ["zeit", "ziel"]


# ------------------------------------------------------------------ Ganzer Lauf
def _handelstage(von: date, bis: date) -> list[date]:
    tage, d = [], von
    while d <= bis:
        if d.weekday() < 5:
            tage.append(d)
        d += timedelta(days=1)
    return tage


def _metall_archive(k: dict) -> None:
    tage = _handelstage(date(2008, 1, 2), date(2026, 9, 25))
    texte = [t.isoformat() for t in tage]
    chip = [e for e in k["ereignisse"] if e["art"] == "verschaerfung" and "chip" in e["achsen"]]
    spruenge = []
    for e in chip:
        i0 = next(i for i, t in enumerate(texte) if t >= str(e["datum"]))
        spruenge.append((i0 + 5, i0 + 30))
    o = konfig.DATEN / "metall" / "china" / "kurse"
    for inst in k["instrumente"] + [k["vergleich"]]:
        reihe = []
        for i, t in enumerate(texte):
            wert = 50.0 if inst["ticker"] == "XME" else 10.0
            if inst.get("achse") == "chip" and any(a <= i < b for a, b in spruenge):
                wert = 13.5
            reihe.append({"datum": t, "schluss": wert, "volumen": 1_000_000})
        kurse.ergaenze_archiv(kurse.archiv_pfad(o, inst["ticker"]), reihe)


def _ersatz_daten() -> None:
    sprung = {date(2004, 4, 13), date(2014, 4, 8), date(2019, 4, 23)}   # eine Woche nach dem Einstieg
    o = konfig.DATEN / "ersatz" / "haselnuss"
    for ticker in ("SHV.AX", "^AXJO"):
        wert, reihe = 1.0 if ticker == "SHV.AX" else 5000.0, []
        for t in _handelstage(date(2000, 1, 3), date(2026, 9, 25)):
            if ticker == "SHV.AX" and t in sprung:
                wert *= 1.25
            reihe.append({"datum": t.isoformat(), "schluss": round(wert, 4), "volumen": 3_000_000})
        kurse.ergaenze_archiv(kurse.archiv_pfad(o / "kurse", ticker), reihe)
    faelle = [{"datum": d, "jahr": int(d[:4])} for d in ("2004-04-04", "2014-03-31", "2019-04-13")]
    speicher.schreibe_json(o / "rueckblick.json", {"werte": {"SHV.AX": {"faelle": faelle}}})


def _palmoel_daten() -> None:
    m0 = bilanz.monats_index("1997-09")
    reihe = []
    for i in range(bilanz.monats_index("1990-01"), bilanz.monats_index("2026-06") + 1):
        k = i - m0
        wert = 100 + 40 * k / 6 if 0 <= k <= 6 else 140 - 4 * (k - 6) if 6 < k <= 16 else 100.0
        reihe.append({"datum": bilanz.monat_text(i) + "-01", "wert": round(wert, 4)})
    speicher.schreibe_json(konfig.GESCHICHTE / "preise.json", {"reihen": {"palmoel": reihe}})
    speicher.schreibe_json(konfig.RUECKBLICK / "palmoel.json", {
        "einstellungen": {"lernzeit_bis": "2015-12"},
        "lernzeit": {"bilanz": {"signale": [{"monat": "1997-09", "schluss": "1999-01"},
                                            {"monat": "2015-06", "schluss": None}]}}})


def test_ganzer_lauf(ablage):
    k = konfig.lade_yaml(konfig.KONFIG / "metalle" / "china.yaml")
    _metall_archive(k)
    _ersatz_daten()
    _palmoel_daten()
    zeit = konfig.jetzt().replace(year=2026, month=9, day=27)
    e = ausstieg.lauf(zeit)

    chip = e["zweige"]["metall_china"]["achsen"]["chip"]
    assert (chip["faelle_gesamt"], chip["verglichen"]) == (6, 6)
    v = {x["kennung"]: x for x in chip["varianten"]}
    assert v["bisher"]["mittel"] == 0.0 and v["zeit"]["mittel"] == 0.35 and v["ziel"]["mittel"] == 0.35
    assert v["nachlauf"]["mittel"] == 0.0 and v["kombi"]["mittel"] == 0.0
    assert v["ziel"]["dauer"] == 5 and v["bisher"]["gruende"] == {"nach 90 Tagen": 6}
    assert chip["vorn_gleichauf"] == ["zeit", "ziel"] and chip["gipfel_mittel"] == 0.35

    magnet = e["zweige"]["metall_china"]["achsen"]["magnet"]
    assert (magnet["faelle_gesamt"], magnet["verglichen"], magnet["offen"]) == (18, 16, 2)   # neun Verschärfungen, zwei Werte
    gruende = next(x for x in magnet["varianten"] if x["kennung"] == "bisher")["gruende"]
    assert gruende.get("Lockerung") == 2                       # Oktober 2025: Busan drei Wochen später

    hasel = e["zweige"]["ersatz_haselnuss"]
    assert hasel["status"] == "ok" and hasel["verglichen"] == 3
    hv = {x["kennung"]: x for x in hasel["varianten"]}
    assert hv["bisher"]["mittel"] == 0.25 and hv["bisher"]["gruende"] == {"Ende der Ernte": 3}
    assert hv["ziel"]["gruende"] == {"Gewinnziel": 3} and hv["ziel"]["dauer"] == 6

    palm = e["zweige"]["palmoel"]
    assert (palm["verglichen"], palm["offen"]) == (1, 1) and palm["massstab"] == "mittel"
    pv = {x["kennung"]: x for x in palm["varianten"]}
    assert pv["bisher"]["mittel"] == 0.0 and pv["zeit"]["mittel"] == 0.16 and pv["ziel"]["mittel"] == 0.2
    assert pv["nachlauf"]["mittel"] == 0.16 and pv["kombi"]["mittel"] == 0.24 and palm["vorn"] == "kombi"

    ausstieg_text.schreibe(e, konfig.ABGABE)
    gesamt = ""
    for t in sorted(konfig.ABGABE.glob("ausstieg-teil-*.md")):
        text = t.read_text(encoding="utf-8")
        assert len(text) <= vorlesen.GRENZE
        rumpf = text.split("\n", 2)[2]
        assert not re.search(r"\d", rumpf), rumpf
        gesamt += rumpf + " "
    assert "Chip-Achse mit Perpetua Resources und United States Antimony: sechs Fälle." in gesamt
    assert "Gewinnziel dreißig Prozent: plus fünfunddreißig Prozent, gegen den Vergleich fünfunddreißig Prozentpunkte vorn" in gesamt
    assert "Vorn beim Ergebnis: Verlustgrenze fünfzehn Prozent" in gesamt
    assert "Gleichauf vorn beim Vorsprung: Nach zwanzig Handelstagen und Gewinnziel dreißig Prozent." in gesamt
    assert "Zwei sind noch nicht abgeschlossen und zählen nicht mit." in gesamt
    assert "Alle Regeln liegen gleichauf." in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    status = (konfig.ABGABE / "status-ausstieg.md").read_text(encoding="utf-8")
    assert "Vorn: Chip-Achse zeit/ziel" in status


def test_ohne_rueckblicke(ablage):
    e = ausstieg.lauf(konfig.jetzt())
    assert e["zweige"]["palmoel"]["status"] == "Rückblick fehlt"
    assert e["zweige"]["ersatz_haselnuss"]["status"] == e["zweige"]["ersatz_palladium"]["status"] == "Rückblick fehlt"
    assert e["zweige"]["metall_china"]["status"] == "keine Kurse"
    ausstieg_text.schreibe(e, konfig.ABGABE)
    text = (konfig.ABGABE / "ausstieg-teil-1.md").read_text(encoding="utf-8")
    assert "Palmöl: folgt, sobald der erste Rückblick gelaufen ist." in text
