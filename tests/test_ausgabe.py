"""Sprache, Vorlesetext, Logbuch, Kalender, Formulare."""
from datetime import date

import pytest

from anlage import kalender, konfig, logbuch, speicher
from anlage.ausgabe import sprache, vorlesen


@pytest.mark.parametrize("zahl, text", [
    (0, "null"), (1, "eins"), (16, "sechzehn"), (21, "einundzwanzig"), (30, "dreißig"),
    (101, "einhunderteins"), (987, "neunhundertsiebenundachtzig"), (1000, "eintausend"),
    (2026, "zweitausendsechsundzwanzig"), (31001, "einunddreißigtausendeins"), (-3, "minus drei"),
])
def test_zahlwoerter(zahl, text):
    assert sprache.wort(zahl) == text


def test_komma_prozent_datum():
    assert sprache.komma(0.83, 2) == "null Komma acht drei"
    assert sprache.komma(1.2, 1, vorzeichen=True) == "plus eins Komma zwei"
    assert sprache.komma(-0.04, 1) == "null"
    assert sprache.komma(-0.4, 1) == "minus null Komma vier"
    assert sprache.komma(2.0, 2) == "zwei"
    assert sprache.prozent(0.824) == "zweiundachtzig Prozent"
    assert sprache.veraenderung(-0.124) == "zwölf Prozent gefallen"
    assert sprache.datum(date(2026, 9, 25)) == "fünfundzwanzigsten September"
    assert sprache.datum(date(2026, 10, 1)) == "ersten Oktober"
    assert sprache.datum(date(2026, 10, 3)) == "dritten Oktober"


def _stand_mit_langem_text(anzahl: int) -> dict:
    rohstoffe = {f"r{i}": {"name": f"Rohstoff {i}", "ampel": {"farbe": "Gelb", "zahl": 5, "gesperrt": False,
                                                          "farbe_rechnung": "Gelb", "veto": [],
                                                          "gruende": ["Zeitfenster knapp: nein"],
                                                          "rot_bedingungen": [{"name": "Zeitfenster knapp",
                                                                               "erfuellt": False}]}}
                 for i in range(anzahl)}
    return {"stand": "2026-09-26T04:31:00+02:00", "datum": "2026-09-26", "zustand": "in Ordnung",
            "rohstoffe": rohstoffe, "klima": {}, "quellen": {}, "kalender": [], "hinweise": [], "logbuch_neu": []}


def test_vorlesetext_teilt_und_stempelt(tmp_path):
    stand = _stand_mit_langem_text(120)
    teile = vorlesen.teile(stand)
    assert len(teile) > 1
    for nr, teil in enumerate(teile, start=1):
        zeilen = teil.split("\n")
        assert zeilen[0] == "Stand: 26.09.2026, 04:31"
        assert zeilen[1] == f"Teil {nr} von {len(teile)}"
        assert len(teil) <= vorlesen.GRENZE
    (tmp_path / "anlage-teil-9.md").write_text("alt")
    pfade = vorlesen.schreibe(stand, tmp_path)
    assert not (tmp_path / "anlage-teil-9.md").exists()
    assert len(pfade) == len(teile)
    status = (tmp_path / "status-anlage.md").read_text().splitlines()
    assert len(status) == 5 and status[2] == "Zustand: in Ordnung"


def test_vorlesetext_ohne_ziffern_im_text():
    stand = _stand_mit_langem_text(1)
    koerper = "\n".join(vorlesen.teile(stand)[0].split("\n")[2:])
    assert not any(z.isdigit() for z in koerper.replace("Rohstoff 0", ""))


def test_logbuch_start_wechsel_und_schattenkauf(tmp_path):
    pfad = tmp_path / "signale.jsonl"
    def bewertung(farbe):
        return {"palmoel": {"ampel": {"farbe": farbe, "zahl": 7, "gesperrt": False, "gruende": []},
                            "preisprobe": {"letzter": {"datum": "2027-06-01", "wert": 880.0}},
                            "instrumente": [{"ticker": "EB5.SI", "kurs": 1.5, "datum": "2027-08-13"}]}}
    assert logbuch.ergaenze(pfad, "t1", bewertung("Gelb"))[0]["anlass"] == "Start"
    assert logbuch.ergaenze(pfad, "t2", bewertung("Gelb")) == []
    neu = logbuch.ergaenze(pfad, "t3", bewertung("Rot"))
    assert neu[0]["vorher"] == "Gelb" and neu[0]["schattenkauf"] is True
    assert neu[0]["kurse"] == {"EB5.SI": {"kurs": 1.5, "datum": "2027-08-13"}}
    assert len(logbuch.lies(pfad)) == 2


def test_kalender_faustregel_und_monatsende():
    k = {"vorschau_tage": 7, "berichte": [{"name": "MPOB", "tag_im_monat": 10, "genau": False},
                                          {"name": "Fest", "termine": ["2026-10-02"], "genau": True},
                                          {"name": "Ultimo", "tag_im_monat": 31}]}
    liste = kalender.naechste(k, date(2026, 9, 26))
    assert [(e["name"], e["datum"]) for e in liste] == [("Ultimo", "2026-09-30"), ("Fest", "2026-10-02")]
    liste = kalender.naechste(k, date(2026, 10, 5))
    assert [(e["name"], e["datum"]) for e in liste] == [("MPOB", "2026-10-10")]
    assert kalender.naechste(k, date(2026, 11, 25))[0]["datum"] == "2026-11-30"


def test_alle_formulare_sind_gueltig():
    k = konfig.konfiguration()
    assert k["rohstoffe"], "kein Rohstoff-Formular gefunden"
    for kennung, eintrag in k["rohstoffe"].items():
        assert konfig.pruefe_rohstoff(eintrag, k["regionen"]) == [], kennung
        for g in eintrag.get("gegenkraefte", []):
            assert g["kennung"] in k["quellen"]["yahoo"]["gegenkraefte"], f"{kennung}: Gegenkraft {g['kennung']} ohne Ticker"


def test_fehlerhaftes_formular_wird_erkannt():
    fehler = konfig.pruefe_rohstoff({"name": "X", "kennung": "x", "familie": "C", "treiber": "klima",
                                     "rolle": "kandidat", "kopplungen": [], "preis": {"quelle": "fred"},
                                     "instrumente": [{"name": "ohne Ticker"}],
                                     "indikator": {"region": "sued"}}, {"ost": {}})
    text = " | ".join(fehler)
    for teil in ("„familie“", "ausloeser", "serie", "Ticker fehlt", "Region „sued“"):
        assert teil in text


def test_regenarchiv_abrufbeginn():
    heute = date(2026, 9, 26)
    bedarf = date(2025, 10, 1)
    assert speicher.regen_abrufbeginn({}, bedarf, heute) == bedarf
    voll = {"2025-09-01": 1.0, "2026-09-20": 2.0}
    assert speicher.regen_abrufbeginn(voll, bedarf, heute) == date(2026, 6, 18)
    alt = {"2025-09-01": 1.0, "2026-01-10": 2.0}
    assert speicher.regen_abrufbeginn(alt, bedarf, heute) == date(2025, 12, 31)
    zusammen = speicher.regen_zusammenfuehren({"2026-09-01": 3.0}, {"2026-09-01": None, "2026-09-02": 1.0},
                                              date(2026, 1, 1))
    assert zusammen == {"2026-09-01": 3.0, "2026-09-02": 1.0}


def test_schattendepot_nur_einmal_offen_und_veto_wechsel(tmp_path):
    pfad = tmp_path / "signale.jsonl"

    def b(farbe, gesperrt=False):
        return {"palmoel": {"ampel": {"farbe": farbe, "zahl": 7, "gesperrt": gesperrt, "gruende": []},
                            "instrumente": []}}
    assert logbuch.ergaenze(pfad, "1", b("Rot", gesperrt=True))[0]["schattenkauf"] is False
    aufgehoben = logbuch.ergaenze(pfad, "2", b("Rot"))[0]
    assert aufgehoben["anlass"] == "Veto aufgehoben" and aufgehoben["schattenkauf"] is True
    assert logbuch.ergaenze(pfad, "3", b("Gelb"))[0]["schattenkauf"] is False
    assert logbuch.ergaenze(pfad, "4", b("Rot"))[0]["schattenkauf"] is False      # Position ist noch offen
    assert logbuch.ergaenze(pfad, "5", b("Grün"))[0]["schattenschluss"] is True
    assert logbuch.ergaenze(pfad, "6", b("Rot"))[0]["schattenkauf"] is True
    assert logbuch.ergaenze(pfad, "7", b("ohne Urteil")) == []
    assert logbuch.letzter_stand(logbuch.lies(pfad))["palmoel"]["farbe"] == "Rot"


def test_yahoo_tabelle_ohne_laufenden_handelstag():
    pd = pytest.importorskip("pandas")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from anlage.quellen import kurse
    zone = "Asia/Singapore"
    index = pd.DatetimeIndex([pd.Timestamp(t, tz=zone) for t in ("2026-09-24", "2026-09-25", "2026-09-26")])
    tabelle = pd.DataFrame({"Close": [1.0, float("nan"), 3.0], "Volume": [100, 0, 50]}, index=index)
    vormittag = kurse.tabelle_zu_reihe(tabelle, datetime(2026, 9, 26, 10, 30, tzinfo=ZoneInfo(zone)))
    assert [e["datum"] for e in vormittag] == ["2026-09-24"]
    abend = kurse.tabelle_zu_reihe(tabelle, datetime(2026, 9, 26, 19, 0, tzinfo=ZoneInfo(zone)))
    assert [(e["datum"], e["volumen"]) for e in abend] == [("2026-09-24", 100), ("2026-09-26", 50)]
