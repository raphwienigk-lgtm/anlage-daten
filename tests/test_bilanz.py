"""Bilanz: Signale wie im Schattendepot, Treffer, Mehrwert, große Bewegungen, Urteil."""
from __future__ import annotations

import pytest

from anlage import bilanz

S_RB = {"treffer_ab": 0.20, "bewegung_ab": 0.30, "erkannt_monate_vorher": 6,
        "bestehen": {"mehrwert_ab": 0.10, "mindest_signale": 1, "treffer_mindestens_wie_fehlalarme": True,
                     "zufall_hoechstens": 0.5}}


def monate(von: str, bis: str) -> list[str]:
    return [bilanz.monat_text(i) for i in range(bilanz.monats_index(von), bilanz.monats_index(bis) + 1)]


def verlauf(farben: dict[str, str], von="2000-01", bis="2003-12", episode: tuple[str, str] | None = None,
            gesperrt: set[str] = frozenset()) -> list[dict]:
    liste = []
    for m in monate(von, bis):
        in_episode = episode is not None and episode[0] <= m <= episode[1]
        liste.append({"monat": m, "farbe": farben.get(m, "Grün"), "episode": in_episode,
                      "gesperrt": m in gesperrt, "fehlt": ["Zeitfenster knapp"] if farben.get(m) == "Gelb" else []})
    return liste


def preise(werte: dict[str, float], von="1999-01", bis="2004-12", standard=100.0) -> list[dict]:
    return [{"datum": f"{m}-01", "wert": werte.get(m, standard)} for m in monate(von, bis)]


def rampe(von: str, bis: str, a: float, b: float) -> dict[str, float]:
    liste = monate(von, bis)
    return {m: a + (b - a) * k / (len(liste) - 1) for k, m in enumerate(liste)}


def test_monate_hin_und_zurueck():
    assert bilanz.monat_text(bilanz.monats_index("1997-08-01")) == "1997-08"
    assert bilanz.monats_index("1998-01") - bilanz.monats_index("1997-12") == 1


def test_signale_wie_im_schattendepot():
    v = verlauf({"2000-03": "Rot", "2000-04": "Gelb", "2000-05": "Rot", "2000-06": "ohne Urteil",
                 "2000-07": "Gelb", "2001-01": "Rot", "2001-02": "Rot", "2002-05": "Rot"},
                gesperrt={"2002-05"})
    liste = bilanz.signale(v)
    assert [(s["monat"], s["schluss"]) for s in liste] == [("2000-03", "2000-08"), ("2001-01", "2001-03")]


def test_signale_aus_logbuch():
    eintraege = [
        {"zeit": "2027-08-15T04:30:00+02:00", "rohstoff": "palmoel", "farbe": "Rot", "schattenkauf": True, "zahl": 7},
        {"zeit": "2027-09-02T04:30:00+02:00", "rohstoff": "kakao", "farbe": "Rot", "schattenkauf": True},
        {"zeit": "2028-01-10T04:30:00+01:00", "rohstoff": "palmoel", "farbe": "Grün", "schattenschluss": True},
    ]
    liste = bilanz.signale_aus_logbuch(eintraege, "palmoel")
    assert len(liste) == 1
    assert liste[0]["monat"] == "2027-08" and liste[0]["schluss"] == "2028-01" and liste[0]["zahl"] == 7


def test_treffer_fehlalarm_offen():
    p = bilanz.preis_nach_monat(preise({**rampe("2000-03", "2000-08", 100, 125), "2000-09": 118, "2001-03": 110}))
    s = bilanz.bewerte_signal({"monat": "2000-03", "schluss": "2000-10"}, p, 0.20)
    assert s["urteil"] == "Treffer"
    assert s["hoechster"] == pytest.approx(0.25)
    assert s["gipfel_nach_monaten"] == 5
    assert s["nach_12"] == pytest.approx(0.10)
    assert s["bei_schluss"] == pytest.approx(0.0)

    p = bilanz.preis_nach_monat(preise(rampe("2000-03", "2000-08", 100, 110)))
    assert bilanz.bewerte_signal({"monat": "2000-03"}, p, 0.20)["urteil"] == "Fehlalarm"

    p = bilanz.preis_nach_monat(preise({}), bis=bilanz.monats_index("2000-12"))
    offen = bilanz.bewerte_signal({"monat": "2000-03"}, p, 0.20)
    assert offen["urteil"] == "offen" and offen["nach_3"] == pytest.approx(0.0)


def test_grenze_haelt_spaetere_preise_fern():
    """Ein Signal kurz vor Ende der Lernzeit bleibt offen, auch wenn spätere Preise vorliegen."""
    v = verlauf({"2002-06": "Rot"})
    p = preise(rampe("2002-07", "2003-03", 100, 150))
    mit = bilanz.bilanz(v, p, "2000-01", "2003-12", S_RB)
    ohne = bilanz.bilanz(v, p, "2000-01", "2002-12", S_RB, preis_bis="2002-12")
    assert mit["signale"][0]["urteil"] == "Treffer"
    assert ohne["signale"][0]["urteil"] == "offen"
    assert ohne["bewertbar"] == 0


def test_mehrwert_und_urteil():
    werte = {**rampe("2001-02", "2001-08", 100, 160), **{m: 160 for m in monate("2001-09", "2004-12")}}
    v = verlauf({"2001-01": "Rot", "2001-02": "Rot"}, episode=("2000-06", "2001-01"))
    b = bilanz.bilanz(v, preise(werte), "2000-01", "2003-12", S_RB)
    assert b["anzahl"] == 1 and b["treffer"] == 1 and b["fehlalarme"] == 0
    assert b["mittel_12"] == pytest.approx(0.60)
    assert b["mehrwert"] == pytest.approx(b["mittel_12"] - b["basis_12"], abs=1e-4)
    assert b["mehrwert"] > 0.10
    assert b["urteil"]["bestanden"] is True
    assert b["farben"]["Rot"] == 2


def test_urteil_gruende():
    b = S_RB["bestehen"]
    zahlen = {"bewertbar": 4, "mehrwert": 0.05, "treffer": 1, "fehlalarme": 3, "zufall_anteil": 0.7}
    arten = [g["art"] for g in bilanz.urteil(zahlen, b)["gruende"]]
    assert arten == ["mehrwert", "fehlalarme", "zufall"]
    zu_wenig = bilanz.urteil({**zahlen, "bewertbar": 0}, {**b, "mindest_signale": 3})
    assert [g["art"] for g in zu_wenig["gruende"]] == ["zu_wenige"]


def test_zufallsprobe():
    alle = [0.0] * 50 + [0.5] * 50
    p = bilanz.zufallsprobe(alle, 5, 0.5)
    assert 0.015 < p < 0.045                                     # etwa C(50,5)/C(100,5) = 0,028
    assert bilanz.zufallsprobe(alle, 5, 0.0) == 1.0
    assert bilanz.zufallsprobe(alle, 0, 0.1) is None


def test_bewegungen_eingeordnet():
    werte = {}
    werte.update(rampe("2000-06", "2000-12", 100, 140))           # A: Rot vorher, rechtzeitig, El Niño
    werte.update({m: 100 for m in monate("2001-01", "2001-05")})
    werte.update(rampe("2001-06", "2001-12", 100, 150))           # B: Rot erst mittendrin, spät
    werte.update({m: 100 for m in monate("2002-01", "2002-05")})
    werte.update(rampe("2002-06", "2002-12", 100, 150))           # C: nur Gelb vorher
    werte.update({m: 100 for m in monate("2003-01", "2003-05")})
    werte.update(rampe("2003-06", "2003-12", 100, 150))           # D: verpasst
    werte.update({m: 100 for m in monate("2004-01", "2004-12")})
    farben = {"2000-03": "Rot", **{m: "Gelb" for m in monate("2000-04", "2000-11")}, "2000-12": "Grün",
              "2001-09": "Rot", "2001-12": "Grün",
              "2002-02": "Gelb"}
    v = verlauf(farben, von="1999-06", bis="2003-12", episode=("1999-06", "2000-06"))
    hoehepunkt = [bilanz.monats_index("2000-03")]                  # Fenster Dezember 1999 bis März 2001
    b = bilanz.bilanz(v, preise(werte, bis="2005-06"), "1999-06", "2003-12", S_RB, ereignisse=hoehepunkt)
    ergebnis = [(g["beginn"], g["einordnung"], g["el_nino"]) for g in b["bewegungen"]]
    assert ergebnis == [("2000-06", "rechtzeitig", True), ("2001-06", "spät", False),
                        ("2002-06", "nur Gelb", False), ("2003-06", "verpasst", False)]
    assert b["bewegungen"][0]["rot_seit"] == "2000-03"
    assert b["bewegungen"][1]["anstieg"] == pytest.approx(0.50)
    z = b["bewegungen_zaehlung"]
    assert z["gesamt"] == 4 and z["mit_el_nino"] == 1 and z["el_nino"]["rechtzeitig"] == 1


def test_engpaesse_zaehlen_gelb_monate():
    v = verlauf({"2000-02": "Gelb", "2000-03": "Gelb", "2000-04": "Rot"})
    b = bilanz.bilanz(v, preise({}), "2000-01", "2003-12", S_RB)
    assert b["engpaesse"] == {"Zeitfenster knapp": 2}


def test_position_aus_der_zeit_davor_ist_kein_neues_signal():
    v = verlauf({"1978-11": "Rot", "1978-12": "Rot", "1979-01": "Rot", "1979-02": "Gelb"},
                von="1978-01", bis="1980-12")
    p = preise({}, von="1977-01", bis="1982-12")
    ganz = bilanz.bilanz(v, p, "1978-01", "1980-12", S_RB)
    spaeter = bilanz.bilanz(v, p, "1979-01", "1980-12", S_RB)
    assert [s["monat"] for s in ganz["signale"]] == ["1978-11"]
    assert spaeter["anzahl"] == 0


def test_el_nino_ohne_ereignisse_zaehlt_der_monat_des_beginns():
    werte = {**rampe("2001-06", "2001-12", 100, 150), **{m: 150 for m in monate("2002-01", "2004-12")}}
    mit = bilanz.bilanz(verlauf({}, episode=("2001-06", "2001-06")), preise(werte), "2000-01", "2003-12", S_RB)
    ohne = bilanz.bilanz(verlauf({}, episode=("2000-01", "2001-05")), preise(werte), "2000-01", "2003-12", S_RB)
    assert [g["el_nino"] for g in mit["bewegungen"]] == [True]
    assert [g["el_nino"] for g in ohne["bewegungen"]] == [False]
