"""Rechenwege: El Niño, Zeugen, Kaskade, Checkliste, Score, Ampel, Veto."""
from datetime import date, timedelta

import pytest

from anlage.module import dipol, enso, regenzeugen
from anlage.quellen import klimaindizes
from anlage.rechnen import bewerten, kennzahlen
from conftest import el_nino_2026, oni_text


def _oni(bis):
    return klimaindizes.lies_oni(oni_text({k: v for k, v in el_nino_2026().items() if k <= bis}))


# ------------------------------------------------------------------ Kennzahlen
def test_zwert():
    assert kennzahlen.zwert([1, 2, 3], 5) is None
    assert kennzahlen.zwert([5, 5, 5], 3) is None
    assert kennzahlen.zwert([1, 2, 3, 4, 10], 5) == pytest.approx(1.9, abs=0.05)


def test_veraenderung_und_volumen():
    reihe = [{"datum": (date(2026, 1, 1) + timedelta(days=k)).isoformat(), "schluss": 100 + k, "volumen": 10}
             for k in range(120)]
    assert kennzahlen.veraenderung(reihe, 91) == pytest.approx(219 / 128 - 1)
    assert kennzahlen.volumen_trend(reihe) == pytest.approx(1.0)


# ------------------------------------------------------------------ El Niño
def test_enso_laufende_episode_hoehepunkt_noch_offen(schwellen):
    lage = enso.lage(_oni((2026, 11)), schwellen["enso"], date(2026, 12, 10), 12)
    ep = lage["episode"]
    assert lage["phase"] == "El Niño" and lage["stufe1"]
    assert ep["laeuft"] and not ep["hoehepunkt_bestaetigt"]
    assert ep["beginn"]["jahreszeit"] == "MJJ" and ep["ab"] == "2026-05-01"
    assert enso.zeitfenster(lage, 12)["wert"] == 1.0


def test_enso_hoehepunkt_bestaetigt_und_zeitfenster(schwellen):
    lage = enso.lage(_oni((2027, 6)), schwellen["enso"], date(2027, 8, 15), 12)
    ep = lage["episode"]
    assert lage["phase"] == "neutral"
    assert not ep["laeuft"] and ep["hoehepunkt_bestaetigt"]
    assert ep["hoehepunkt"]["jahreszeit"] == "NDJ" and ep["hoehepunkt"]["jahr"] == 2026
    assert ep["monate_seit_hoehepunkt"] == 8
    assert lage["staerke"] == pytest.approx(0.95)
    zf = enso.zeitfenster(lage, 12)
    assert zf["wert"] == pytest.approx(0.333, abs=0.001) and zf["status"] == "läuft"


def test_enso_alte_episode_zaehlt_nicht_mehr(schwellen):
    lage = enso.lage(_oni((2027, 6)), schwellen["enso"], date(2028, 7, 1), 12)
    assert lage["episode"] is None
    assert enso.zeitfenster(lage, 12)["status"] == "kein Ereignis"


def test_enso_erster_tag_und_episodenjahre(schwellen):
    assert enso.erster_tag({"jahr": 2027, "monat": 1}) == date(2026, 12, 1)
    assert enso.erster_tag({"jahr": 2026, "monat": 8}) == date(2026, 7, 1)
    laufend = enso.lage(_oni((2026, 11)), schwellen["enso"], date(2026, 12, 10), 12)
    assert enso.episode_jahre(laufend, date(2026, 12, 10)) == [2026]
    vorbei = enso.lage(_oni((2027, 6)), schwellen["enso"], date(2027, 8, 15), 12)
    assert enso.episode_jahre(vorbei, date(2027, 8, 15)) == [2026]


# ------------------------------------------------------------------ Regenzeugen
def _tage(von: date, bis: date, wert):
    d, aus = von, {}
    while d <= bis:
        aus[d.isoformat()] = wert(d) if callable(wert) else wert
        d += timedelta(days=1)
    return aus


NORMAL_OST = {"A": {f"{m:02d}-{t:02d}": 8.0 for m in range(1, 13) for t in range(1, 32)},
              "B": {f"{m:02d}-{t:02d}": 8.0 for m in range(1, 13) for t in range(1, 32)}}


def test_ostzeuge_aktuell_und_verlauf(schwellen):
    s = schwellen["zeugen"]["ost"]
    trocken = (date(2026, 7, 1), date(2026, 10, 31))
    wert = lambda d: 4.0 if trocken[0] <= d <= trocken[1] else 8.0
    daten = {"A": _tage(date(2026, 1, 1), date(2027, 8, 10), wert),
             "B": _tage(date(2026, 1, 1), date(2027, 8, 10), wert)}
    heute_stand = regenzeugen.ostzeuge(daten, NORMAL_OST, s)
    assert heute_stand["anteil"] == 1.0 and heute_stand["an"] is False
    verlauf = regenzeugen.ostzeuge_verlauf(daten, NORMAL_OST, s, date(2026, 5, 1))
    assert verlauf["an"] is True
    assert verlauf["tiefster_anteil"] == pytest.approx(0.5)
    assert verlauf["erster_trockener_tag"] == "2026-08-14"   # 45 von 90 Tagen halb trocken → genau 75 %


def test_ostzeuge_verlauf_braucht_genug_messwerte(schwellen):
    s = schwellen["zeugen"]["ost"]
    luecken = {"A": {d: (w if int(d[8:]) % 3 else None) for d, w in _tage(date(2026, 1, 1), date(2026, 7, 31), 4.0).items()}}
    assert regenzeugen.ostzeuge_verlauf(luecken, NORMAL_OST, s, date(2026, 5, 1))["status"] == "zu wenige Messwerte"


def test_westzeuge_saison_und_ausser_saison(schwellen):
    s = schwellen["zeugen"]["west"]
    normal = {"W": {f"{m:02d}-{t:02d}": 3.0 for m in range(1, 13) for t in range(1, 32)}}
    daten = {"W": _tage(date(2025, 9, 1), date(2026, 12, 29), 5.4)}
    zu_jung = regenzeugen.westzeuge(daten, normal, s, date(2026, 10, 15))
    assert zu_jung["status"] == "Saison zu jung" and zu_jung["an"] is None
    laeuft = regenzeugen.westzeuge(daten, normal, s, date(2026, 11, 20))
    assert laeuft["status"] == "läuft" and laeuft["an"] is True and laeuft["anteil"] == pytest.approx(1.8)
    ausser = regenzeugen.westzeuge(daten, normal, s, date(2026, 9, 26))
    assert ausser["status"] == "außer Saison" and ausser["saison_ab"] == "2026-10-01"
    assert ausser["letzte_saison"]["jahr"] == 2025 and ausser["letzte_saison"]["status"] == "abgeschlossen"


def test_westzeuge_verlauf_zaehlt_saisons_der_episode(schwellen):
    s = schwellen["zeugen"]["west"]
    normal = {"W": {f"{m:02d}-{t:02d}": 3.0 for m in range(1, 13) for t in range(1, 32)}}
    daten = {"W": _tage(date(2026, 1, 1), date(2027, 8, 10),
                        lambda d: 5.4 if date(2026, 10, 1) <= d <= date(2026, 12, 31) else 3.0)}
    v = regenzeugen.westzeuge_verlauf(daten, normal, s, date(2026, 5, 1), date(2027, 8, 15))
    assert v["an"] is True and [x["jahr"] for x in v["saisons"]] == [2026]
    frueh = regenzeugen.westzeuge_verlauf(daten, normal, s, date(2026, 5, 1), date(2026, 9, 1))
    assert frueh["an"] is None and "noch keine Regenzeit" in frueh["status"]


# ------------------------------------------------------------------ Kaskade
def test_dipol_stufen_und_kreuz(schwellen):
    sd = schwellen["dipol"]
    s2 = dipol.stufe2({2026: {"anomalie_ms": -1.5, "vollstaendig": True},
                       2027: {"anomalie_ms": 0.1, "vollstaendig": True}}, date(2027, 8, 15), sd, [2026])
    assert s2["an"] is True and s2["grundlage"] == "Episode" and s2["aktuell"]["an"] is False
    frueh = dipol.stufe2({}, date(2026, 3, 1), sd, [])
    assert frueh["an"] is None and "noch nicht fällig" in frueh["aktuell"]["status"]
    dmi = [{"jahr": 2026, "monat": m, "wert": w} for m, w in [(9, 0.9), (10, 1.0), (11, 0.2)]]
    s3 = dipol.stufe3(dmi, "JMA", sd, date(2026, 5, 1))
    assert s3["an"] is True and s3["aktuell"]["an"] is False
    assert s3["hoechster_seit_beginn"] == {"wert": 1.0, "monat": "2026-10"}
    assert dipol.kreuzbestaetigung({"an": True}, {"an": True})["bestaetigt"]
    assert dipol.kreuzbestaetigung({"an": True}, {"an": None, "status": "Saison zu jung"})["urteil"] == "Westzeuge ohne Urteil"
    assert dipol.kreuzbestaetigung({"an": True}, {"an": False})["urteil"] == "nur Osten"


def test_prognose_veraltet():
    p = dipol.prognose({"bom_iod_prognose": {"stand": "2026-09-01", "aussage": "positiv"}}, date(2026, 9, 30))
    assert p["status"] == "veraltet" and p["alter_tage"] == 29
    assert dipol.prognose({"bom_iod_prognose": {"stand": None}}, date(2026, 9, 30))["status"] == "nicht eingetragen"


# ------------------------------------------------------------------ Score, Ampel, Veto
def test_score_grenzen_und_fehlende_faktoren(schwellen):
    s = schwellen["agrar_ampel"]
    assert bewerten.score(1.0, 1.0, -1.0, 0.0, s)["zahl"] == 10
    assert bewerten.score(0.0, 0.0, 3.0, 1.0, s)["zahl"] == 1
    assert bewerten.score(0.95, 0.333, -0.5, 0.0, s)["zahl"] == 8
    ohne = bewerten.score(1.0, 1.0, None, None, s)
    assert ohne["zahl"] == 10 and set(ohne["fehlend"]) == {"zwert", "gegenkraefte"}


def test_gegenkraefte_druck(schwellen):
    s = schwellen["agrar_ampel"]
    reihe = lambda rueckgang: [{"datum": "2026-01-01", "schluss": 100.0},
                               {"datum": "2026-04-15", "schluss": 100.0 * (1 - rueckgang)}]
    rohstoff = {"gegenkraefte": [{"kennung": "brent", "text": "Öl"}, {"kennung": "soja", "text": "Soja"}]}
    g = bewerten.gegenkraefte(rohstoff, {"brent": reihe(0.2), "soja": reihe(0.04)}, s)
    assert g["einzeln"]["brent"]["druck"] == 1.0 and g["einzeln"]["soja"]["druck"] == pytest.approx(0.2)
    assert g["wert"] == pytest.approx(0.6) and g["ueberwiegen"] is True


def test_veto_wirkungen():
    heute = date(2026, 10, 5)
    grund = {"farbe": "Rot", "zahl": 8, "gruende": []}
    veto = {"aktiv": [{"rohstoff": "palmoel", "wirkung": "sperren", "seit": "2026-10-01", "grund": "Exportstopp"}]}
    gesperrt = bewerten.veto_anwenden(grund, "palmoel", veto, heute)
    assert gesperrt["gesperrt"] and gesperrt["anzeige"] == "gesperrt (Rot, 8)"
    abgelaufen = {"aktiv": [{"rohstoff": "palmoel", "wirkung": "sperren", "bis": "2026-10-01"}]}
    assert not bewerten.veto_anwenden(grund, "palmoel", abgelaufen, heute)["gesperrt"]
    hoch = bewerten.veto_anwenden({"farbe": "Grün", "zahl": None, "gruende": []}, "palmoel",
                                  {"aktiv": [{"rohstoff": "palmoel", "wirkung": "hochstufen"}]}, heute)
    assert hoch["farbe"] == "Gelb" and hoch["farbe_rechnung"] == "Grün"
    runter = bewerten.veto_anwenden(grund, "palmoel", {"aktiv": [{"rohstoff": "palmoel", "wirkung": "herabstufen"}]}, heute)
    assert runter["anzeige"] == "Gelb, 8"
    fremd = bewerten.veto_anwenden(grund, "kakao", veto, heute)
    assert fremd["anzeige"] == "Rot, 8" and fremd["veto"] == []


def test_ampel_gruen_ohne_ausloeser(schwellen):
    s = schwellen["agrar_ampel"]
    punkte = [{"nr": 1, "status": "nein", "text": "kein El Niño, der noch wirkt"},
              {"nr": 2, "status": "nein", "text": ""}, {"nr": 3, "status": "ja", "text": ""},
              {"nr": 4, "status": "ja", "text": ""}]
    a = bewerten.ampel({"kopplungen": ["enso", "dipol"]}, punkte, {"wert": None}, None, None, s)
    assert a["farbe"] == "Grün" and a["zahl"] is None


def test_ampel_rot_nur_mit_kreuzbestaetigung(schwellen):
    s = schwellen["agrar_ampel"]
    punkte = [{"nr": n, "status": "ja", "text": ""} for n in range(1, 5)]
    zf = {"wert": 0.33}
    sc = {"zahl": 8}
    lage = {"ostende_bestaetigt": True, "kreuz": {"bestaetigt": True, "urteil": "bestätigt"}}
    assert bewerten.ampel({"kopplungen": ["enso", "dipol"]}, punkte, zf, lage, sc, s)["farbe"] == "Rot"
    nur_ost = {"ostende_bestaetigt": True, "kreuz": {"bestaetigt": False, "urteil": "nur Osten"}}
    gelb = bewerten.ampel({"kopplungen": ["enso", "dipol"]}, punkte, zf, nur_ost, sc, s)
    assert gelb["farbe"] == "Gelb" and gelb["gruende"] == ["Kreuzbestätigung West und Ost: nur Osten"]
    weit = bewerten.ampel({"kopplungen": ["enso"]}, punkte, {"wert": 0.8}, None, sc, s)
    assert weit["farbe"] == "Gelb" and weit["gruende"] == ["Zeitfenster knapp: nein"]


# ------------------------------------------------------------------ Episodenregeln (nach der Durchsicht)
def _reihe(werte: dict):
    return klimaindizes.lies_oni(oni_text(werte))


def test_einzelner_ausreisser_nach_der_episode_zaehlt_nicht(schwellen):
    werte = {k: v for k, v in el_nino_2026().items() if k <= (2027, 6)}
    werte[(2027, 7)] = 0.1
    werte[(2027, 8)] = 0.5                              # einzelne Jahreszeit ab +0,5, läuft gerade
    lage = enso.lage(_reihe(werte), schwellen["enso"], date(2027, 9, 20), 12)
    assert lage["episode"]["hoehepunkt"]["wert"] == 1.9     # die alte Episode bleibt maßgeblich
    assert lage["neue_erwaermung"]["laenge_jahreszeiten"] == 1


def test_eine_jahreszeit_knapp_darunter_trennt_die_episode_nicht(schwellen):
    werte = {k: v for k, v in el_nino_2026().items() if k <= (2027, 6)}
    werte[(2026, 8)] = 0.45
    lage = enso.lage(_reihe(werte), schwellen["enso"], date(2027, 8, 15), 12)
    assert lage["episode"]["ab"] == "2026-05-01"


def test_kurze_abgeschlossene_folge_ist_keine_episode(schwellen):
    werte = {(2025, m): 0.0 for m in range(1, 13)}
    werte.update({(2025, 3): 0.6, (2025, 4): 0.7, (2025, 5): 0.6})
    assert enso.lage(_reihe(werte), schwellen["enso"], date(2026, 1, 20), 12)["episode"] is None


def test_gleichstand_am_hoehepunkt_nimmt_den_spaeteren(schwellen):
    werte = {(2026, m): 0.0 for m in range(1, 5)}
    werte.update({(2026, 5): 0.6, (2026, 6): 1.2, (2026, 7): 1.0, (2026, 8): 1.2, (2026, 9): 0.9})
    lage = enso.lage(_reihe(werte), schwellen["enso"], date(2026, 10, 20), 12)
    assert lage["episode"]["hoehepunkt"]["jahreszeit"] == "JAS"
    assert lage["episode"]["hoehepunkt_bestaetigt"] is False


def test_episodenjahre_bei_spaetem_beginn():
    lage = {"episode": {"ab": "2026-12-01", "laeuft": False, "hoehepunkt_bestaetigt": True,
                        "hoehepunkt": {"jahr": 2027, "monat": 3}}}
    assert enso.episode_jahre(lage, date(2027, 9, 1)) == []
    lage = {"episode": {"ab": "2014-10-01", "laeuft": False, "hoehepunkt_bestaetigt": True,
                        "hoehepunkt": {"jahr": 2015, "monat": 12}}}
    assert enso.episode_jahre(lage, date(2016, 9, 1)) == [2014, 2015]


def test_duerre_vor_der_episode_zaehlt_nicht(schwellen):
    s = schwellen["zeugen"]["ost"]
    trocken_vorher = lambda d: 4.0 if date(2026, 2, 1) <= d <= date(2026, 4, 30) else 8.0
    daten = {"A": _tage(date(2025, 12, 1), date(2026, 10, 1), trocken_vorher)}
    verlauf = regenzeugen.ostzeuge_verlauf(daten, NORMAL_OST, s, date(2026, 5, 1))
    assert verlauf["an"] is False
    nach_ende = regenzeugen.ostzeuge_verlauf(
        {"A": _tage(date(2026, 1, 1), date(2027, 12, 1), lambda d: 4.0 if d.year == 2027 and d.month > 6 else 8.0)},
        NORMAL_OST, s, date(2026, 5, 1), bis=date(2027, 5, 31))
    assert nach_ende["an"] is False and nach_ende["bis"] == "2027-05-31"


def test_wind_urteil_erst_nach_mindesttagen(schwellen):
    sd = schwellen["dipol"]
    frueh = dipol.stufe2({2026: {"anomalie_ms": -2.0, "vollstaendig": False, "tage": 5}}, date(2026, 5, 12), sd, None)
    assert frueh["an"] is None and "erst 5 Tage" in frueh["aktuell"]["status"]
    spaeter = dipol.stufe2({2026: {"anomalie_ms": -2.0, "vollstaendig": False, "tage": 20}}, date(2026, 5, 27), sd, None)
    assert spaeter["an"] is True
    leer = dipol.stufe2({}, date(2027, 9, 1), sd, [])
    assert leer["an"] is None and leer["grundlage"] == "Episode"


def test_handeingabe_mit_falschem_datum():
    p = dipol.prognose({"bom_iod_prognose": {"stand": "23.09.2026", "aussage": "positiv"}}, date(2026, 9, 30))
    assert p["status"] == "Datum unlesbar" and "JJJJ-MM-TT" in p["fehler"]


def test_veto_mit_falschem_datum_oder_wirkung():
    grund = {"farbe": "Rot", "zahl": 8, "gruende": []}
    veto = {"aktiv": [{"rohstoff": "palmoel", "wirkung": "sperren", "seit": "2026-10-2", "grund": "Test"},
                      {"rohstoff": "palmoel", "wirkung": "stoppen"}]}
    ergebnis = bewerten.veto_anwenden(grund, "palmoel", veto, date(2026, 10, 5))
    assert not ergebnis["gesperrt"] and len(ergebnis["veto_fehler"]) == 2


def test_zahl_wahlweise_ohne_zeitfenster(schwellen):
    s = dict(schwellen["agrar_ampel"])
    mit = bewerten.score(0.5, 0.1, -0.5, 0.0, s)["zahl"]       # Zeitfenster fast zu: drückt die Zahl
    ohne = bewerten.score(0.5, None, -0.5, 0.0, s)["zahl"]     # nur Güte: Stärke, Preisprobe, Gegenkräfte
    assert (mit, ohne) == (7, 9)


def test_ampel_ohne_urteil_wenn_ausloeser_unbekannt(schwellen):
    punkte = [{"nr": 1, "status": "unbekannt", "text": "El-Niño-Index heute nicht lesbar"}] + \
             [{"nr": n, "status": "ja", "text": ""} for n in (2, 3, 4)]
    a = bewerten.ampel({"kopplungen": []}, punkte, {"wert": None}, None, None, schwellen["agrar_ampel"])
    assert a["farbe"] == bewerten.OHNE_URTEIL
    assert bewerten.veto_anwenden(a, "palmoel", {"aktiv": [{"rohstoff": "palmoel", "wirkung": "hochstufen"}]},
                                  date(2026, 1, 1))["farbe"] == bewerten.OHNE_URTEIL


def test_gegenkraefte_mit_monatswerten_genau_drei_monate():
    from anlage.rechnen import bewerten
    rohstoff = {"gegenkraefte": [{"kennung": "brent", "text": "Brent"}]}
    reihe = [{"datum": f"2026-{m:02d}-01", "schluss": w} for m, w in ((1, 100.0), (2, 90.0), (3, 90.0), (4, 80.0))]
    s = {"gegen_voll_bei": 0.20, "gegenkraefte_ueberwiegen_ab": 0.6}
    tageskurs = bewerten.gegenkraefte(rohstoff, {"brent": reihe}, s)            # 91 Tage: April → Dezember fehlt
    monatlich = bewerten.gegenkraefte(rohstoff, {"brent": reihe}, {**s, "gegen_tage": 89})
    assert tageskurs["einzeln"]["brent"]["veraenderung_3m"] is None
    assert monatlich["einzeln"]["brent"]["veraenderung_3m"] == pytest.approx(-0.2)
