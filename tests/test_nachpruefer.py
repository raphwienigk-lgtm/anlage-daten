"""Nachprüfer: Laufkontrolle, Ampel der Woche, Schattendepot, Signalbilanz, Vorlesetext."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest

from anlage import konfig, nachpruefer, speicher
from anlage.ausgabe import vorlesen
from anlage.quellen import kurse


def _logbuch(eintraege: list[dict]) -> None:
    pfad = konfig.DATEN / "signale.jsonl"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eintraege), encoding="utf-8")


def _eintrag(tag: str, farbe: str, vorher=None, anlass="Farbwechsel", kauf=False, schluss=False,
             kurs=None, preis=None) -> dict:
    return {"zeit": f"{tag}T04:31:00+02:00", "rohstoff": "palmoel", "farbe": farbe, "zahl": 8 if farbe == "Rot" else None,
            "gesperrt": False, "vorher": vorher, "anlass": anlass, "gruende": [], "schattenkauf": kauf,
            "schattenschluss": schluss, "rohstoffpreis": preis,
            "kurse": {"F34.SI": {"kurs": kurs, "datum": tag}} if kurs else {}}


def _szenario(bis_schluss: bool = True) -> None:
    eintraege = [
        _eintrag("2027-06-01", "Gelb", anlass="Start"),
        _eintrag("2027-08-16", "Rot", "Gelb", kauf=True, kurs=3.0, preis={"datum": "2027-06-01", "wert": 1000.0}),
    ]
    if bis_schluss:
        eintraege.append(_eintrag("2027-12-01", "Grün", "Rot", schluss=True, kurs=3.6,
                                  preis={"datum": "2027-10-01", "wert": 1300.0}))
    _logbuch(eintraege)
    reihe, tag = [], date(2027, 8, 16)
    while tag <= date(2027, 12, 3):
        if tag.weekday() < 5:
            wert = 3.0 + 0.6 * (tag - date(2027, 8, 16)).days / 107
            if tag == date(2027, 9, 1):
                wert = 2.7                                           # Rücksetzer
            reihe.append({"datum": tag.isoformat(), "schluss": round(wert, 4), "volumen": 1000})
        tag += timedelta(days=1)
    kurse.ergaenze_archiv(kurse.archiv_pfad(konfig.PREISE, "F34.SI"), reihe)
    speicher.schreibe_json(konfig.PREISE / "fred_PPOILUSDM.json",
                           [{"datum": f"2027-{m:02d}-01", "wert": 1000.0 + 50 * (m - 6)} for m in range(1, 12)])
    speicher.schreibe_json(konfig.DATEN / "stand.json", {"datum": "2027-12-05", "zustand": "in Ordnung", "hinweise": []})


def _laeufe(pfad, heute: date, fehlt: set[int]) -> str:
    laeufe = [{"conclusion": "success", "createdAt": f"{(heute - timedelta(days=k)).isoformat()}T02:41:00Z"}
              for k in range(7) if k not in fehlt]
    laeufe.append({"conclusion": "failure", "createdAt": f"{(heute - timedelta(days=2)).isoformat()}T02:41:00Z"})
    datei = pfad / "laeufe.json"
    datei.write_text(json.dumps(laeufe), encoding="utf-8")
    return str(datei)


def test_geschlossene_position_und_laufkontrolle(ablage):
    _szenario()
    assert nachpruefer.main(["--heute", "2027-12-05", "--laeufe", _laeufe(ablage, date(2027, 12, 5), {2})]) == 0
    e = speicher.lies_json(konfig.DATEN / "nachpruefer.json")
    lk = e["laufkontrolle"]
    assert lk["tage_mit_lauf"] == 6 and lk["fehlende_tage"] == ["2027-12-03"]
    r = e["rohstoffe"]["palmoel"]
    assert r["ampel"]["farbe"] == "Grün" and r["ampel"]["seit"] == "2027-12-01"
    assert [w["farbe"] for w in r["ampel"]["wechsel"]] == ["Grün"]
    p = r["positionen"][0]
    assert not p["offen"] and p["tage"] == 107
    inst = p["instrumente"][0]
    assert inst["name"] == "Wilmar International"
    assert inst["veraenderung"] == pytest.approx(0.2)
    assert inst["tiefster"] == pytest.approx(-0.1)
    assert p["rohstoff"]["veraenderung"] == pytest.approx(0.3)
    assert r["signale"]["anzahl"] == 1 and r["signale"]["offen"] == 1
    assert r["vorschlag_faellig"] is False


def test_offene_position_bewertet_mit_dem_archiv(ablage):
    _szenario(bis_schluss=False)
    assert nachpruefer.main(["--heute", "2027-09-10"]) == 0
    e = speicher.lies_json(konfig.DATEN / "nachpruefer.json")
    p = e["rohstoffe"]["palmoel"]["positionen"][0]
    assert p["offen"] and p["tage"] == 25
    inst = p["instrumente"][0]
    assert inst["art"] == "heute" and inst["ende_datum"] == "2027-12-03"   # Archiv reicht im Test weiter
    assert e["laufkontrolle"]["tage_mit_lauf"] is None


def test_vorlesetext_im_format(ablage):
    _szenario()
    nachpruefer.main(["--heute", "2027-12-05", "--laeufe", _laeufe(ablage, date(2027, 12, 5), set())])
    teile = sorted(konfig.ABGABE.glob("nachpruefer-teil-*.md"))
    assert teile
    for nr, pfad in enumerate(teile, start=1):
        text = pfad.read_text(encoding="utf-8")
        zeilen = text.split("\n")
        assert zeilen[0].startswith("Stand: ") and zeilen[1] == f"Teil {nr} von {len(teile)}"
        assert len(text) <= vorlesen.GRENZE
        assert not re.search(r"\d", "\n".join(zeilen[2:])), "Zahlen müssen ausgeschrieben sein"
    gesamt = " ".join(p.read_text(encoding="utf-8") for p in teile)
    assert "Der tägliche Lauf gelang an allen sieben Tagen." in gesamt
    assert "Wilmar International plus zwanzig Prozent" in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    assert (konfig.ABGABE / "status-nachpruefer.md").exists()


def test_ohne_logbuch(ablage):
    assert nachpruefer.main(["--heute", "2026-09-27"]) == 0
    text = (konfig.ABGABE / "nachpruefer-teil-1.md").read_text(encoding="utf-8")
    assert "noch kein Eintrag im Logbuch" in text and "keine gedachte Position" in text


def test_laufkontrolle_zaehlt_erst_ab_betriebsbeginn():
    heute = date(2026, 9, 29)
    laeufe = [{"conclusion": "success", "createdAt": "2026-09-27T02:41:00Z"},
              {"conclusion": "success", "createdAt": "2026-09-29T02:41:00Z"}]
    lk = nachpruefer.laufkontrolle(laeufe, heute, None, date(2026, 9, 27))
    assert lk["tage_gezaehlt"] == 3 and lk["tage_mit_lauf"] == 2 and lk["fehlende_tage"] == ["2026-09-28"]
    vorher = nachpruefer.laufkontrolle([], date(2026, 9, 26), None, date(2026, 9, 27))
    assert vorher["tage_gezaehlt"] == 0 and vorher["fehlende_tage"] == []


def test_text_vor_betriebsbeginn(ablage):
    assert nachpruefer.main(["--heute", "2026-09-26", "--laeufe", _laeufe(ablage, date(2026, 9, 26), set(range(7)))]) == 0
    text = (konfig.ABGABE / "nachpruefer-teil-1.md").read_text(encoding="utf-8")
    assert "noch nicht in Betrieb; der erste ist für den siebenundzwanzigsten September geplant" in text
    assert "Zustand: in Ordnung" in (konfig.ABGABE / "status-nachpruefer.md").read_text(encoding="utf-8")
    # Die Vorlesezeit wächst mit der Zahl der Zweige; geprüft wird, dass sie überhaupt ausgewiesen ist.
    assert "Vorlesezeit" in (konfig.ABGABE / "status-nachpruefer.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ andere Zweige (seit 26.09.2026)
def _zweige_szenario(ordner) -> None:
    tage = [date(2026, 9, 27) + timedelta(days=i) for i in range(8)]            # bis Sonntag, 4. Oktober
    m = konfig.DATEN / "metall" / "china"
    for t in tage:
        chip = "Gelb" if t >= date(2026, 10, 1) else "Grün"
        speicher.haenge_zeile_an(m / "verlauf.jsonl", {"zeit": f"{t}T01:20:00+02:00", "datum": t.isoformat(),
                                                        "stufen": {"chip": chip, "magnet": "Grün", "batterie": "Grün",
                                                                   "werkzeug": "Grün"}})
    o = konfig.DATEN / "ersatz" / "haselnuss"
    for t in tage[1:]:
        speicher.haenge_zeile_an(o / "verlauf.jsonl", {"zeit": f"{t}T04:10:00+02:00", "datum": t.isoformat(),
                                                        "stufe": "Grün", "phase": "außer Saison"})
    speicher.schreibe_json(o / "schattendepot.json", {"positionen": [
        {"zeit": "2026-09-28T04:10:00+02:00", "grund": "Rot", "kurse": {"SHV.AX": {"kurs": 4.0, "datum": "2026-09-25"}},
         "vergleich": {"^AXJO": {"kurs": 8000.0, "datum": "2026-09-25"}}}]})
    for ticker, werte in (("SHV.AX", (4.0, 4.4)), ("^AXJO", (8000.0, 8080.0))):
        kurse.ergaenze_archiv(kurse.archiv_pfad(o / "kurse", ticker),
                              [{"datum": "2026-09-25", "schluss": werte[0], "volumen": 1}, {"datum": "2026-10-02", "schluss": werte[1], "volumen": 1}])
    # Metall läuft um 23:17 UTC, also am Vorabend nach UTC; Ersatz fehlt am 30. September; Inlandspreise ohne Datei
    metall = [{"conclusion": "success", "createdAt": f"{t - timedelta(days=1)}T23:18:00Z"} for t in tage]
    ersatz = [{"conclusion": "success", "createdAt": f"{t}T02:09:00Z"} for t in tage if t != date(2026, 9, 30)]
    (ordner / "metall.json").write_text(json.dumps(metall), encoding="utf-8")
    (ordner / "ersatz.json").write_text(json.dumps(ersatz), encoding="utf-8")


def test_andere_zweige(ablage):
    ordner = ablage / "laeufe"
    ordner.mkdir()
    _zweige_szenario(ordner)
    assert nachpruefer.main(["--heute", "2026-10-04", "--laeufe-ordner", str(ordner)]) == 0
    e = speicher.lies_json(konfig.DATEN / "nachpruefer.json")
    w = {x["workflow"]: x for x in e["weitere_laeufe"]}
    assert w["metall"]["tage_mit_lauf"] == 7 and w["metall"]["fehlende_tage"] == []
    assert w["ersatz"]["tage_gezaehlt"] == 7 and w["ersatz"]["fehlende_tage"] == ["2026-09-30"]
    assert w["inlandspreise"]["tage_mit_lauf"] is None
    chip = e["zweige"]["metall_china"]["achsen"]["chip"]
    assert chip["jetzt"] == "Gelb" and chip["seit"] == "2026-10-01" and chip["wechsel"] == [
        {"tag": "2026-10-01", "vorher": "Grün", "jetzt": "Gelb"}]
    hasel = e["zweige"]["ersatz_haselnuss"]
    assert hasel["jetzt"] == "Grün" and hasel["seit_beginn"] and hasel["positionen"][0]["offen"]
    assert hasel["positionen"][0]["instrumente"][0]["veraenderung"] == 0.1 and hasel["positionen"][0]["vergleich"] == 0.01

    teile = sorted(konfig.ABGABE.glob("nachpruefer-teil-*.md"))
    gesamt = " ".join(p.read_text(encoding="utf-8").split("\n", 2)[2] for p in teile)
    assert not re.search(r"\d", gesamt)
    assert ("Die anderen täglichen Läufe: Metall China an allen sieben Tagen; Ersatz-Sensoren an sechs von sieben Tagen, "
            "es fehlte am dreißigsten September; Inlandspreise unbekannt; Schattendepot unbekannt.") in gesamt
    assert "Chip-Achse steht auf Gelb seit dem ersten Oktober" in gesamt
    assert "Wechsel in dieser Woche: Chip-Achse am ersten Oktober von Grün auf Gelb." in gesamt
    assert "Ersatz-Sensor Haselnuss steht auf Grün seit Beginn der Aufzeichnung am achtundzwanzigsten September." in gesamt
    assert "Select Harvests plus zehn Prozent" in gesamt and "Der Vergleichsmaßstab, australischer Aktienindex ASX zweihundert, im selben Zeitraum: plus ein Prozent." in gesamt
    assert "Zustand: Warnung" in (konfig.ABGABE / "status-nachpruefer.md").read_text(encoding="utf-8")
