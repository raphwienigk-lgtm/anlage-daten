"""Rückblick von Anfang bis Ende mit einer erfundenen Geschichte.

Erfunden: ein starker El Niño 1997/98 (Höhepunkt November bis Januar mit +2,4), Dürre auf
Sumatra und Borneo von Juli bis November 1997, eine nasse kurze Regenzeit in Ostafrika,
starke Ostwinde im Mai und Juni 1997, Dipol positiv im Herbst 1997. Der Palmölpreis fällt
lange leicht und steigt ab Juli 1998 um vierzig Prozent. Die Lernzeit endet im Dezember 1999.
"""
from __future__ import annotations

import copy
import re
from datetime import date, timedelta

import pytest

from anlage import geschichte, konfig, netz, rueckblick, speicher
from anlage.ausgabe import vorlesen
from anlage.netz import AbrufFehler
from anlage.quellen import klimaindizes

from conftest import _monate

HEUTE = "2002-06-10"
ONI_1997 = {(1997, 5): 0.4, (1997, 6): 0.8, (1997, 7): 1.2, (1997, 8): 1.6, (1997, 9): 1.9, (1997, 10): 2.1,
            (1997, 11): 2.3, (1997, 12): 2.4, (1998, 1): 2.2, (1998, 2): 1.8, (1998, 3): 1.3, (1998, 4): 0.8,
            (1998, 5): 0.4}


def _preis_palmoel() -> list[dict]:
    reihe = []
    for i, (j, m) in enumerate(_monate((1990, 1), (2002, 5))):
        if (j, m) <= (1998, 6):
            wert = 560 - 0.6 * i                                   # lange leicht fallend: der Markt schläft
        elif (j, m) <= (1999, 4):
            start = 560 - 0.6 * 101
            wert = start * (1 + 0.40 * ((j - 1998) * 12 + m - 6) / 10)
        else:
            wert = (560 - 0.6 * 101) * 1.40
        reihe.append({"datum": f"{j}-{m:02d}-01", "wert": round(wert, 2)})
    return reihe


def geschichte_anlegen(k: dict, status_fertig: bool = True) -> None:
    regionen = k["regionen"]
    # El Niño und Dipol als gespeicherter Stand (das Netz ist im Test aus)
    oni = [{"jahreszeit": klimaindizes.JAHRESZEITEN[m - 1], "jahr": j, "monat": m, "wert": ONI_1997.get((j, m), 0.0)}
           for j, m in _monate((1990, 1), (2002, 3))]
    speicher.schreibe_json(konfig.KLIMA / "oni.json", {"geholt": "2002-06-01", "reihe": oni})
    dmi = [{"jahr": j, "monat": m, "wert": 0.8 if (1997, 8) <= (j, m) <= (1997, 11) else 0.0}
           for j, m in _monate((1990, 1), (2002, 4))]
    speicher.schreibe_json(konfig.KLIMA / "dmi.json", {"geholt": "2002-06-01", "quelle": "Test", "reihe": dmi})

    # Regen: Normal und Geschichte
    normal, orte = {}, {}
    start, ende = date(1993, 10, 1), date(2002, 6, 1)
    for region, wert in (("ost", 8.0), ("west", 3.0)):
        for p in regionen[region]["punkte"]:
            normal[p["name"]] = {f"{m:02d}-{t:02d}": wert for m in range(1, 13) for t in range(1, 32)}
            orte[p["name"]] = {"lat": p["lat"], "lon": p["lon"]}
            werte, tag = {}, start
            while tag <= ende:
                if region == "ost":
                    werte[tag.isoformat()] = 4.0 if date(1997, 7, 1) <= tag <= date(1997, 11, 30) else 8.0
                elif tag.month >= 10:
                    werte[tag.isoformat()] = 5.4 if tag.year == 1997 else 3.0
                tag += timedelta(days=1)
            geschichte.schreibe_gz(geschichte.regen_pfad(p["name"]),
                                   {"punkt": p["name"], "region": region, "ort": orte[p["name"]],
                                    "werte": werte, "fertig": []})
    speicher.schreibe_json(konfig.KLIMA / "regen.json", {"punkte": normal, "orte": orte, "fertig": True})

    # Wind: Normal −3 m/s, 1997 um 1,5 m/s stärker aus Osten
    wind_punkte, wind_orte = {}, {}
    for p in regionen["wind_sumatra"]["punkte"]:
        wind_punkte[p["name"]] = {"mittel_ms": -3.0,
                                  "je_jahr": {str(j): (-4.5 if j == 1997 else -3.0) for j in range(1991, 2002)}}
        wind_orte[p["name"]] = {"lat": p["lat"], "lon": p["lon"]}
    speicher.schreibe_json(konfig.KLIMA / "wind.json", {"punkte": wind_punkte, "orte": wind_orte, "fertig": True})
    speicher.schreibe_json(konfig.GESCHICHTE / "wind.json", {"punkte": {}})

    # Preise: Palmöl wie oben, Gegenkräfte ruhig
    ruhig = [{"datum": f"{j}-{m:02d}-01", "wert": 100.0} for j, m in _monate((1990, 1), (2002, 5))]
    speicher.schreibe_json(konfig.GESCHICHTE / "preise.json", {
        "reihen": {"palmoel": _preis_palmoel(), "brent": ruhig, "sojaoel": ruhig},
        "herkunft": {"palmoel": "Test", "brent": "Test", "sojaoel": "Test"}})
    speicher.schreibe_json(konfig.GESCHICHTE / "ernte.json", {"reihen": {
        "Indonesia": {str(j): 1000 * 1.08 ** (j - 1990) * (0.9 if j == 1998 else 1.0) for j in range(1990, 2002)},
        "Malaysia": {str(j): 2000 * 1.05 ** (j - 1990) for j in range(1990, 2002)}}})
    speicher.schreibe_json(konfig.GESCHICHTE / "status.json", {
        "preise": {"fertig": True}, "wind": {"fertig": True}, "regen": {"fertig": status_fertig}})


@pytest.fixture
def k_test(ablage, monkeypatch):
    k = copy.deepcopy(konfig.konfiguration())
    rb = k["schwellen"]["rueckblick"]
    rb.update({"beginn": "1994-01", "lernzeit_bis": "1999-12", "wetter_unsicher_bis": 1995})
    rb["bestehen"] = {**rb["bestehen"], "mindest_signale": 1, "zufall_hoechstens": 0.5}
    monkeypatch.setattr(konfig, "konfiguration", lambda: copy.deepcopy(k))

    def netz_aus(url, params=None):
        raise AbrufFehler(f"Netz im Test aus: {url}")

    monkeypatch.setattr(netz, "hole_text", netz_aus)
    geschichte_anlegen(k)
    return k


def _nach_monat(ergebnis: dict, teil: str = "lernzeit") -> dict[str, dict]:
    return {e["monat"]: e for e in ergebnis[teil]["verlauf"]}


def test_zeitmaschine_findet_rot_zur_richtigen_zeit(k_test):
    assert rueckblick.main(["--heute", HEUTE]) == 0
    e = speicher.lies_json(konfig.RUECKBLICK / "palmoel.json")
    v = _nach_monat(e)
    assert len(v) == 72
    # Höhepunkt NDJ 1997 ist erst bestätigt, wenn zwei niedrigere Jahreszeiten veröffentlicht sind
    assert v["1998-03"]["zf"] == 1.0
    assert v["1998-04"]["zf"] == pytest.approx(0.667)
    # Die erste Jahreszeit über +0,5 (Mitte Juni) ist erst ab August veröffentlicht
    assert v["1997-07"]["ostende"] is False and v["1997-07"]["episode"] is False
    assert v["1997-08"]["ostende"] is True and v["1997-08"]["episode"] is True
    # Rot, sobald das Zeitfenster knapp ist; Grün, wenn es abgelaufen ist
    assert v["1998-05"]["farbe"] == "Gelb" and "Zeitfenster knapp" in v["1998-05"]["fehlt"]
    assert v["1998-06"]["farbe"] == "Rot"
    assert v["1998-12"]["farbe"] == "Grün"
    assert v["1996-06"]["farbe"] == "Grün"

    b = e["lernzeit"]["bilanz"]
    assert [s["monat"] for s in b["signale"]] == ["1998-06"]
    s = b["signale"][0]
    assert s["urteil"] == "Treffer" and s["schluss"] == "1998-12"
    assert s["hoechster"] == pytest.approx(0.40, abs=0.01)
    assert b["urteil"]["bestanden"] is True
    grosse = [g for g in b["bewegungen"] if g["el_nino"]]
    assert grosse and grosse[0]["einordnung"] == "rechtzeitig"

    ep = e["lernzeit"]["episoden"]
    assert len(ep) == 1 and ep[0]["hoechste_farbe"] == "Rot" and ep[0]["erster_monat"] == "1998-06"
    assert ep[0]["ernte"]["jahr"] == 1998 and ep[0]["ernte"]["delle"] < -0.03

    assert [z["name"] for z in e["lernzeit"]["zeitalter"]] == ["bis 1995", "ab 1996"]
    varianten = {v_["vorlauf_T_monate"]: v_["bilanz"]["signale"] for v_ in e["varianten"]}
    assert varianten == {9: ["1998-05"], 15: ["1998-08"]}
    assert e["pruefzeit"]["status"] == "verschlossen"
    buch = speicher.lies_json(konfig.RUECKBLICK / "pruefzeit.json")
    assert buch == {"palmoel": {"grenze": "1999-12"}}              # nur gemerkt, nichts geöffnet


def test_vorlesetext_im_format(k_test):
    assert rueckblick.main(["--heute", HEUTE]) == 0
    teile = sorted(konfig.ABGABE.glob("rueckblick-palmoel-teil-*.md"))
    assert teile
    for nr, pfad in enumerate(teile, start=1):
        text = pfad.read_text(encoding="utf-8")
        zeilen = text.split("\n")
        assert zeilen[0].startswith("Stand: ")
        assert zeilen[1] == f"Teil {nr} von {len(teile)}"
        assert len(text) <= vorlesen.GRENZE
        assert not re.search(r"\d", "\n".join(zeilen[2:])), "Zahlen müssen ausgeschrieben sein"
    gesamt = " ".join(p.read_text(encoding="utf-8") for p in teile)
    assert "Rot im Juni neunzehnhundertachtundneunzig" in gesamt
    assert "Ergebnis der Lernzeit: bestanden." in gesamt
    assert gesamt.rstrip().endswith("Das ist eine Denkhilfe, keine Anlageberatung.")
    status = (konfig.ABGABE / "status-rueckblick-palmoel.md").read_text(encoding="utf-8")
    assert "Zustand: Lernzeit bestanden, Prüfzeit verschlossen" in status


def test_ohne_vollstaendige_geschichte_kein_rueckblick(k_test):
    geschichte_anlegen(k_test, status_fertig=False)
    assert rueckblick.main(["--heute", HEUTE]) == 1
    assert not (konfig.RUECKBLICK / "palmoel.json").exists()


def test_pruefzeit_wird_festgehalten(k_test, monkeypatch):
    assert rueckblick.main(["--heute", HEUTE, "--pruefzeit-oeffnen", "--ohne-varianten"]) == 0
    buch = speicher.lies_json(konfig.RUECKBLICK / "pruefzeit.json")["palmoel"]["oeffnungen"]
    assert [o["status"] for o in buch] == ["erstmals geöffnet"]
    e = speicher.lies_json(konfig.RUECKBLICK / "palmoel.json")
    assert e["pruefzeit"]["bilanz"]["von"] == "2000-01" and e["pruefzeit"]["bilanz"]["bis"] == "2002-05"

    assert rueckblick.main(["--heute", HEUTE, "--pruefzeit-oeffnen", "--ohne-varianten"]) == 0
    geaendert = copy.deepcopy(k_test)
    geaendert["schwellen"]["rueckblick"]["treffer_ab"] = 0.25
    monkeypatch.setattr(konfig, "konfiguration", lambda: copy.deepcopy(geaendert))
    assert rueckblick.main(["--heute", HEUTE, "--pruefzeit-oeffnen", "--ohne-varianten"]) == 0
    buch = speicher.lies_json(konfig.RUECKBLICK / "pruefzeit.json")["palmoel"]["oeffnungen"]
    assert [o["status"] for o in buch] == ["erstmals geöffnet", "erneut geöffnet, Regeln unverändert",
                                           "erneut geöffnet, Regeln oder Datengrundlage inzwischen geändert"]
    text = " ".join(p.read_text(encoding="utf-8") for p in konfig.ABGABE.glob("rueckblick-palmoel-teil-*.md"))
    assert "nicht mehr unabhängig" in text

    # Ohne Öffnen bleibt sie zu, nennt aber das erste Öffnen
    assert rueckblick.main(["--heute", HEUTE, "--ohne-varianten"]) == 0
    e = speicher.lies_json(konfig.RUECKBLICK / "palmoel.json")
    assert e["pruefzeit"]["status"] == "verschlossen" and len(e["pruefzeit"]["oeffnungen"]) == 3


def test_dipol_quelle_wie_im_taeglichen_lauf(ablage, monkeypatch):
    q = {"dmi": {"urls": [{"name": "JMA", "url": "https://jma.test"}, {"name": "PSL", "url": "https://psl.test"}]}}
    texte = {"https://jma.test": "1958 " + " ".join(["0.1"] * 12) + "\n",
             "https://psl.test": "1870 " + " ".join(["0.2"] * 12) + "\n"}
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: texte[url])
    speicher.schreibe_json(konfig.KLIMA / "dmi.json", {"quelle": "JMA", "reihe": [{"jahr": 1958, "monat": 1, "wert": 0.1}]})
    hinweise = []
    reihe, quelle = rueckblick._dmi(q, 1960, hinweise, {})
    assert quelle == "JMA" and hinweise == []
    # Reicht die Quelle des täglichen Laufs nicht weit genug zurück, gilt die nächste
    reihe, quelle = rueckblick._dmi(q, 1950, hinweise, {})
    assert quelle == "PSL" and reihe[0]["jahr"] == 1870
    assert "der tägliche Lauf JMA" in hinweise[0]
    # JMA heute nicht erreichbar: gespeicherter Stand derselben Quelle
    monkeypatch.setattr(netz, "hole_text", lambda url, params=None: (_ for _ in ()).throw(AbrufFehler("aus")))
    reihe, quelle = rueckblick._dmi(q, 1958, [], {})
    assert quelle == "JMA"


def test_fingerabdruck_reagiert_auf_regeln():
    k = konfig.konfiguration()
    r = k["rohstoffe"]["palmoel"]
    a = rueckblick.fingerabdruck(k, r)
    assert a == rueckblick.fingerabdruck(copy.deepcopy(k), {**r, "instrumente": []})   # Aktien zählen nicht
    k2 = copy.deepcopy(k)
    k2["schwellen"]["agrar_ampel"]["zeitfenster_knapp_ab"] = 0.4
    assert rueckblick.fingerabdruck(k2, r) != a


def test_ostwinde_erst_ab_juli(k_test):
    k = konfig.konfiguration()
    g = rueckblick.lade(k, k["rohstoffe"]["palmoel"], date(1994, 1, 1), date(1999, 12, 28))
    assert g.wind_fuer([1997], date(1997, 6, 15), 7) == {}
    juli = g.wind_fuer([1997], date(1997, 7, 15), 7)[1997]
    assert juli["anomalie_ms"] == pytest.approx(-1.5) and juli["vollstaendig"] is True
    assert g.wind_fuer([1985], date(1985, 8, 15), 7)[1985] == {"fehler": "keine Winddaten für dieses Jahr"}
    assert any("Wind" in h and "fehlen" in h for h in g.hinweise) is False    # 1994 bis 1999 vollständig


def test_regenausschnitt():
    archiv = rueckblick.Regenarchiv({"A": {"2000-01-01": 1.0, "2000-01-02": 2.0, "2000-01-05": 5.0}})
    assert archiv.ausschnitt(["A", "B"], date(2000, 1, 2), date(2000, 1, 4)) == {"A": {"2000-01-02": 2.0}, "B": {}}


def test_verlaengerte_lernzeit_gilt_als_oeffnen(k_test, monkeypatch):
    assert rueckblick.main(["--heute", HEUTE, "--ohne-varianten"]) == 0
    weiter = copy.deepcopy(k_test)
    weiter["schwellen"]["rueckblick"]["lernzeit_bis"] = "2000-12"
    monkeypatch.setattr(konfig, "konfiguration", lambda: copy.deepcopy(weiter))
    assert rueckblick.main(["--heute", HEUTE, "--ohne-varianten"]) == 0
    assert rueckblick.main(["--heute", HEUTE, "--ohne-varianten"]) == 0          # nur einmal festgehalten
    buch = speicher.lies_json(konfig.RUECKBLICK / "pruefzeit.json")["palmoel"]
    assert buch["grenze"] == "2000-12"
    assert [o["status"] for o in buch["oeffnungen"]] == [rueckblick.VERLAENGERT]
    assert rueckblick.main(["--heute", HEUTE, "--ohne-varianten", "--pruefzeit-oeffnen"]) == 0
    e = speicher.lies_json(konfig.RUECKBLICK / "palmoel.json")
    assert e["pruefzeit"]["unabhaengig"] is False


def test_pruefzeit_endet_mit_den_preisen(k_test):
    daten = speicher.lies_json(konfig.GESCHICHTE / "preise.json")
    daten["reihen"]["palmoel"] = [e for e in daten["reihen"]["palmoel"] if e["datum"] <= "2001-06-01"]
    speicher.schreibe_json(konfig.GESCHICHTE / "preise.json", daten)
    assert rueckblick.main(["--heute", HEUTE, "--ohne-varianten", "--pruefzeit-oeffnen"]) == 0
    e = speicher.lies_json(konfig.RUECKBLICK / "palmoel.json")
    assert e["pruefzeit"]["bilanz"]["bis"] == "2001-08"
    assert any("Prüfzeit endet deshalb" in h for h in e["daten"]["hinweise"])
