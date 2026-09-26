"""Probeläufe von Anfang bis Ende mit erfundenen Szenarien, ohne echtes Netz."""
from datetime import date

import pytest

from anlage import klimatologie, konfig, lauf, logbuch, speicher
from anlage.ausgabe import vorlesen
from conftest import WIND_NORMAL, szenario_neutral, szenario_rot


def _klimatologie_bauen():
    assert klimatologie.main(["--pro-minute", "0"]) == 0


def test_klimatologie_baut_normal_und_ist_fortsetzbar(ablage, netz_mit):
    netz = netz_mit(szenario_rot())
    _klimatologie_bauen()
    regen = speicher.lies_json(konfig.KLIMA / "regen.json")
    wind = speicher.lies_json(konfig.KLIMA / "wind.json")
    assert regen["fertig"] and len(regen["punkte"]) == 10
    assert regen["punkte"]["Riau, Sumatra"]["07-01"] == 8.0
    assert regen["punkte"]["Nairobi, Kenia"]["11-15"] == 3.0
    assert all(p["jahre"] == 30 and p["mittel_ms"] == pytest.approx(WIND_NORMAL) for p in wind["punkte"].values())
    abrufe = len(netz.abrufe)
    _klimatologie_bauen()                              # zweiter Start: alles fertig, kein Abruf
    assert len(netz.abrufe) == abrufe


def test_klimatologie_haelt_bei_knappem_budget_an(ablage, netz_mit):
    netz_mit(szenario_rot())
    assert klimatologie.main(["--pro-minute", "75", "--budget-minuten", "0.01"]) == 0
    assert not (konfig.KLIMA / "regen.json").exists()
    status = speicher.lies_json(konfig.KLIMA / "lauf-klimatologie.json")
    assert status["ergebnis"].startswith("Angehalten: Zeitbudget")


def test_klimatologie_verliert_nichts_und_ueberspringt_kaputte_punkte(ablage, netz_mit, monkeypatch):
    from anlage import netz as netzmodul
    from anlage.netz import AbrufFehler
    falsch = netz_mit(szenario_rot())
    k = konfig.konfiguration()
    bengkulu = k["regionen"]["wind_sumatra"]["punkte"][0]
    jambi = k["regionen"]["ost"]["punkte"][1]
    zaehler = {"jambi": 0}

    def launisch(url, params=None):
        if params["latitude"] == bengkulu["lat"]:
            raise AbrufFehler("Fehler 400 bei Open-Meteo: kaputter Punkt")
        if params["latitude"] == jambi["lat"] and "daily" in params:
            zaehler["jambi"] += 1
            if zaehler["jambi"] == 4:
                raise AbrufFehler("Tageslimit oder Ratenlimit erreicht (429) bei Open-Meteo")
        return falsch.hole_json(url, params)

    monkeypatch.setattr(netzmodul, "hole_json", launisch)
    _klimatologie_bauen()
    status = speicher.lies_json(konfig.KLIMA / "lauf-klimatologie.json")
    assert any("Fehler bei Wind vor Bengkulu" in m for m in status["meldungen"])
    assert status["ergebnis"].startswith("Angehalten: Open-Meteo-Limit")
    wind = speicher.lies_json(konfig.KLIMA / "wind.json")
    assert list(wind["punkte"]) == ["südlich der Sundastraße"] and wind["fertig"] is False
    teilweise = speicher.lies_json(konfig.KLIMA / "teilweise.json")
    assert len({d[:4] for d in teilweise["regen"]["Jambi, Sumatra"]["werte"]}) == 15   # drei Blöcke gesichert

    # Zweiter Start: Jambi macht beim vierten Block weiter, ohne die ersten drei neu zu holen
    vorher = zaehler["jambi"]
    _klimatologie_bauen()
    assert zaehler["jambi"] - vorher == 3
    regen = speicher.lies_json(konfig.KLIMA / "regen.json")
    assert regen["fertig"] and regen["jahre_je_punkt"]["Jambi, Sumatra"] == 30
    assert not (konfig.KLIMA / "teilweise.json").exists() or "regen" not in speicher.lies_json(konfig.KLIMA / "teilweise.json")


def test_rot_mit_allen_bedingungen(ablage, netz_mit):
    s = szenario_rot()
    netz_mit(s)
    _klimatologie_bauen()
    stand = lauf.lauf(s.heute, pro_minute=0)
    palm = stand["rohstoffe"]["palmoel"]
    assert palm["ampel"]["anzeige"] == "Rot, 10", palm["ampel"]     # Zahl = Güte, ohne Zeitfenster
    assert palm["score"]["ohne_zeitfenster"] and palm["score"]["fehlend"] == []
    d = stand["klima"]["dipol"]
    assert d["grundlage"] == "Episode" and d["ostende_bestaetigt"]
    assert d["stufe2"]["an"] and d["stufe2"]["episode"][0]["anomalie_ms"] == pytest.approx(-1.5)
    assert d["stufe3"]["hoechster_seit_beginn"]["monat"] == "2026-10"
    assert d["zeugen"]["ost"]["aktuell"]["an"] is False          # heute regnet es wieder normal …
    assert d["zeugen"]["ost"]["episode"]["an"] is True           # … aber die Dürre war da
    assert d["kreuz"]["urteil"] == "bestätigt"
    assert stand["zustand"] == "in Ordnung", stand["quellen"]
    assert [p["status"] for p in palm["checkliste"]] == ["ja", "ja", "ja", "ja"]
    # Logbuch: Startzeile mit Schattenkauf und Kursen
    eintraege = logbuch.lies(konfig.DATEN / "signale.jsonl")
    assert len(eintraege) == 1 and eintraege[0]["schattenkauf"] and len(eintraege[0]["kurse"]) == 4
    # Abgabe
    teil = (konfig.ABGABE / "anlage-teil-1.md").read_text()
    assert teil.startswith("Stand: 15.08.2027") and "\nTeil 1 von 1\n" in teil
    assert "Palmöl steht auf Rot, Zahl zehn, vorläufig." in teil
    assert "Die Kreuzbestätigung steht" in teil
    assert len(teil) <= vorlesen.GRENZE


def test_zweiter_lauf_holt_wenig_und_schreibt_kein_doppeltes_logbuch(ablage, netz_mit):
    s = szenario_rot()
    netz = netz_mit(s)
    _klimatologie_bauen()
    lauf.lauf(s.heute, pro_minute=0)
    vorher = len(netz.abrufe)
    lauf.lauf(s.heute, pro_minute=0)
    neue = netz.abrufe[vorher:]
    regenabrufe = [p for u, p in neue if p and "daily" in p]
    assert len(regenabrufe) == 10
    assert all(p["start_date"] >= "2027-05-07" for p in regenabrufe)      # nur die letzten 100 Tage
    windabrufe = [p for u, p in neue if p and "hourly" in p]
    assert windabrufe == []                                              # Mai/Juni 2026 und 2027 liegen im Zwischenspeicher
    assert len(logbuch.lies(konfig.DATEN / "signale.jsonl")) == 1


def test_gelb_wenn_der_westen_nicht_nass_war(ablage, netz_mit):
    s = szenario_rot()
    s.west_nass = None
    netz_mit(s)
    _klimatologie_bauen()
    palm = lauf.lauf(s.heute, pro_minute=0)["rohstoffe"]["palmoel"]
    assert palm["ampel"]["farbe"] == "Gelb"
    assert palm["ampel"]["gruende"] == ["Kreuzbestätigung West und Ost: nur Osten"]


def test_gelb_wenn_gegenkraefte_ueberwiegen(ablage, netz_mit):
    s = szenario_rot()
    s.kurstrend = {"BZ=F": 0.25, "ZL=F": 0.15}
    netz_mit(s)
    _klimatologie_bauen()
    palm = lauf.lauf(s.heute, pro_minute=0)["rohstoffe"]["palmoel"]
    assert palm["gegenkraefte"]["ueberwiegen"] is True
    assert palm["ampel"]["farbe"] == "Gelb"
    assert "Gegenkräfte überwiegen nicht: nein" in palm["ampel"]["gruende"]


def test_gruen_im_neutralen_jahr_und_westzeuge_ausser_saison(ablage, netz_mit):
    s = szenario_neutral()
    netz_mit(s)
    _klimatologie_bauen()
    stand = lauf.lauf(s.heute, pro_minute=0)
    palm = stand["rohstoffe"]["palmoel"]
    assert palm["ampel"]["anzeige"] == "Grün" and palm["score"] is None
    d = stand["klima"]["dipol"]
    assert d["grundlage"] == "aktuell" and d["zeugen"]["west"]["aktuell"]["status"] == "außer Saison"
    assert d["zeugen"]["west"]["aktuell"]["letzte_saison"]["status"] == "abgeschlossen"
    teil = (konfig.ABGABE / "anlage-teil-1.md").read_text()
    assert "Palmöl steht auf Grün. Grund: kein El Niño, der noch wirkt." in teil
    assert "bis dahin schweigt der Westzeuge" in teil
    assert "um den" not in teil or "Palmölrats" in teil


def test_ohne_klimatologie_laeuft_es_mit_hinweis(ablage, netz_mit):
    s = szenario_rot()
    netz_mit(s)
    stand = lauf.lauf(s.heute, pro_minute=0)
    assert stand["zustand"] == "Warnung"
    assert any("Regen-Klimatologie fehlt" in h for h in stand["hinweise"])
    palm = stand["rohstoffe"]["palmoel"]
    assert palm["ampel"]["farbe"] == "Gelb"          # Zeugen ohne Urteil: kein Rot
    teil = (konfig.ABGABE / "anlage-teil-1.md").read_text()
    assert "Hinweis zur Einrichtung" in teil


def test_ausfaelle_brechen_den_lauf_nicht_ab(ablage, netz_mit):
    s = szenario_rot()
    netz_mit(s)
    _klimatologie_bauen()
    lauf.lauf(s.heute, pro_minute=0)                 # füllt das Preisarchiv
    s.jma_kaputt = True
    s.yahoo_kaputt = {"EB5.SI", "BZ=F"}
    stand = lauf.lauf(s.heute, pro_minute=0)
    dmi = stand["quellen"]["dmi"]                    # JMA fällt aus, der gespeicherte JMA-Stand gilt weiter
    assert dmi["status"] == "ok" and "JMA" in dmi["stand"] and "gespeicherter Stand" in dmi["meldung"]
    assert stand["quellen"]["yahoo:EB5.SI"]["status"] == "Fehler"
    first = next(i for i in stand["rohstoffe"]["palmoel"]["instrumente"] if i["ticker"] == "EB5.SI")
    assert first["kurs"] is not None and first["status"].startswith("Archiv")
    assert stand["rohstoffe"]["palmoel"]["gegenkraefte"]["einzeln"]["brent"]["druck"] is not None
    assert stand["zustand"] == "Warnung"
    assert "nicht erreichbar oder nicht lesbar" in (konfig.ABGABE / "anlage-teil-1.md").read_text()


def test_veto_sperrt(ablage, netz_mit, monkeypatch):
    s = szenario_rot()
    netz_mit(s)
    _klimatologie_bauen()
    echte = konfig.konfiguration

    def mit_veto():
        k = echte()
        k["veto"] = {"aktiv": [{"rohstoff": "palmoel", "wirkung": "sperren", "grund": "Exportstopp",
                                "seit": date(2027, 8, 1)}]}
        return k
    monkeypatch.setattr(konfig, "konfiguration", mit_veto)
    stand = lauf.lauf(s.heute, pro_minute=0)
    ampel = stand["rohstoffe"]["palmoel"]["ampel"]
    assert ampel["anzeige"] == "gesperrt (Rot, 10)"
    assert logbuch.lies(konfig.DATEN / "signale.jsonl")[0]["schattenkauf"] is False
    assert "Veto-Grund: Exportstopp" in (konfig.ABGABE / "anlage-teil-1.md").read_text()


def test_laufende_episode_im_november_ist_gelb_weil_das_fenster_weit_offen_ist(ablage, netz_mit):
    from conftest import dmi_2026, el_nino_2026
    s = szenario_rot()
    s.heute = date(2026, 11, 20)
    s.oni = {k: v for k, v in el_nino_2026().items() if k <= (2026, 10)}
    s.dmi = {k: v for k, v in dmi_2026().items() if k <= (2026, 10)}
    netz_mit(s)
    _klimatologie_bauen()
    stand = lauf.lauf(s.heute, pro_minute=0)
    palm = stand["rohstoffe"]["palmoel"]
    assert palm["zeitfenster"]["wert"] == 1.0
    assert palm["ampel"]["farbe"] == "Gelb" and palm["ampel"]["gruende"] == ["Zeitfenster knapp: nein"]
    d = stand["klima"]["dipol"]
    assert d["zeugen"]["west"]["aktuell"]["status"] == "läuft" and d["zeugen"]["west"]["aktuell"]["an"]
    assert d["kreuz"]["urteil"] == "bestätigt"
    teil = (konfig.ABGABE / "anlage-teil-1.md").read_text()
    assert "Für Rot fehlt noch: das Zeitfenster ist noch weit offen." in teil
    assert "Die Uhr für das Zeitfenster läuft erst ab dem bestätigten Höhepunkt." in teil


def test_ausfall_des_el_nino_index_kippt_die_ampel_nicht(ablage, netz_mit, monkeypatch):
    s = szenario_rot()
    falsch = netz_mit(s)
    _klimatologie_bauen()
    assert lauf.lauf(s.heute, pro_minute=0)["rohstoffe"]["palmoel"]["ampel"]["farbe"] == "Rot"
    echt = falsch.hole_text

    def ohne_oni(url, params=None):
        if "oni.ascii" in url:
            from anlage.netz import AbrufFehler
            raise AbrufFehler("Serverfehler 503")
        return echt(url, params)
    from anlage import netz
    monkeypatch.setattr(netz, "hole_text", ohne_oni)
    stand = lauf.lauf(s.heute, pro_minute=0)
    assert stand["quellen"]["oni"]["status"] == "Fehler" and "gespeicherte Stand" in stand["quellen"]["oni"]["meldung"]
    assert stand["rohstoffe"]["palmoel"]["ampel"]["farbe"] == "Rot"
    assert len(logbuch.lies(konfig.DATEN / "signale.jsonl")) == 1


def test_tippfehler_in_handeingabe_und_veto_stoppen_den_lauf_nicht(ablage, netz_mit, monkeypatch):
    s = szenario_rot()
    netz_mit(s)
    _klimatologie_bauen()
    echte = konfig.konfiguration

    def mit_tippfehlern():
        k = echte()
        k["handeingaben"] = {"bom_iod_prognose": {"stand": "2027-8-1", "aussage": "positiv"}}
        k["veto"] = {"aktiv": [{"rohstoff": "palmoel", "wirkung": "sperren", "seit": "1.8.2027", "grund": "X"}]}
        return k
    monkeypatch.setattr(konfig, "konfiguration", mit_tippfehlern)
    stand = lauf.lauf(s.heute, pro_minute=0)
    assert stand["rohstoffe"]["palmoel"]["ampel"]["anzeige"] == "Rot, 10"
    assert any("handeingaben.yaml" in h for h in stand["hinweise"])
    assert any("veto.yaml" in h for h in stand["hinweise"])
