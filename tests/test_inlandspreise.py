"""Inlandspreise: Leseroutinen, Frühzeichen, Lauf mit erfundenem Netz, Vorlesetext."""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from anlage import inlandspreise, konfig, lauf, netz, speicher
from anlage.ausgabe import vorlesen
from anlage.quellen import inland
from conftest import szenario_rot


def _pihps_antwort(werte: dict[date, float]) -> dict:
    land = {"no": "I", "name": "Semua Provinsi", "level": 0}
    aceh = {"no": "II", "name": "Aceh", "level": 1}
    for d, w in werte.items():
        schluessel = d.strftime("%d/%m/%Y")
        land[schluessel] = f"{int(w):,}"
        aceh[schluessel] = "-"
    return {"data": [land, aceh]}


MPOB_HTML = """<html><body><table>
<tr><th>Day</th><th>Jan</th><th>Feb</th><th>Mar</th></tr>
<tr><td>01</td><td>PH</td><td>4,010.00</td><td>NT</td></tr>
<tr><td>02</td><td>3,967.50</td><td>PH</td><td>4,030.00</td></tr>
<tr><td>30</td><td>3,900.00</td><td></td><td>4,100.50</td></tr>
</table></body></html>"""


def test_zahlen_und_pihps():
    assert inland.zahl("24,350") == 24350 and inland.zahl("3,967.50") == 3967.5
    assert inland.zahl("-") is None and inland.zahl("PH") is None
    reihe = inland.lies_pihps(_pihps_antwort({date(2026, 9, 24): 24350, date(2026, 9, 25): 24400}))
    assert reihe == [{"datum": "2026-09-24", "wert": 24350.0}, {"datum": "2026-09-25", "wert": 24400.0}]
    with pytest.raises(inland.FormatFehler):
        inland.lies_pihps({"data": [{"name": "Aceh", "level": 1}]})


def test_mpob_tabelle_mit_und_ohne_tagesspalte():
    reihe = inland.lies_mpob(MPOB_HTML, 2026)
    assert {"datum": "2026-01-02", "wert": 3967.5} in reihe
    assert {"datum": "2026-03-30", "wert": 4100.5} in reihe
    assert not any(e["datum"] == "2026-02-30" for e in reihe)          # es gibt keinen 30. Februar
    ohne = MPOB_HTML.replace("<th>Day</th>", "")
    assert inland.lies_mpob(ohne, 2026) == reihe
    with pytest.raises(inland.FormatFehler):
        inland.lies_mpob("<table><tr><td>nichts</td></tr></table>", 2026)


def test_fpma():
    reihe = inland.lies_fpma({"datapoints": [{"date": "2026-07-01", "price_value": 21932.0},
                                             {"date": "2026-06-01", "price_value": 21500.0}]})
    assert [e["datum"] for e in reihe] == ["2026-06-01", "2026-07-01"]


def _taeglich(start: date, ende: date, wert) -> list[dict]:
    reihe, d = [], start
    while d <= ende:
        if d.weekday() < 5:
            reihe.append({"datum": d.isoformat(), "wert": wert(d)})
        d += timedelta(days=1)
    return reihe


def test_fruehzeichen_taeglich_und_monatlich(schwellen):
    s = schwellen["inlandspreise"]
    heute = date(2021, 12, 15)
    steigend = _taeglich(date(2021, 6, 1), heute, lambda d: 14000 + 20 * (d - date(2021, 6, 1)).days)
    f = inlandspreise.fruehzeichen(steigend, heute, s)
    assert f["art"] == "täglich" and f["urteil"] in ("Frühzeichen", "starkes Frühzeichen")
    assert f["veraenderung"] == pytest.approx(f["mittel_jetzt"] / f["mittel_damals"] - 1, abs=1e-4)
    ruhig = _taeglich(date(2021, 6, 1), heute, lambda d: 14000)
    assert inlandspreise.fruehzeichen(ruhig, heute, s)["urteil"] == "ruhig"
    assert inlandspreise.fruehzeichen(ruhig[-10:], heute, s)["urteil"] == "zu kurz"
    assert inlandspreise.fruehzeichen(ruhig, heute + timedelta(days=40), s)["urteil"] == "veraltet"
    monat = [{"datum": f"2026-{m:02d}-01", "wert": 20000 + 800 * m} for m in range(1, 8)]
    fm = inlandspreise.fruehzeichen(monat, date(2026, 9, 20), s)
    assert fm["art"] == "monatlich" and fm["vergleich"]["datum"] == "2026-04-01"
    assert fm["veraenderung"] == pytest.approx(25600 / 23200 - 1, abs=1e-4)


def test_lauf_mit_erfundenem_netz(ablage, monkeypatch):
    heute = date(2022, 3, 1)
    abrufe = []

    def falsches_json(url, params=None, kopf=None):
        abrufe.append((url, dict(params or {})))
        if "hargapangan" in url:
            assert kopf and kopf.get("X-Requested-With") == "XMLHttpRequest"
            von, bis = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
            basis = 14000 if params["comcat_id"] == "com_17" else 16000
            werte = {d: basis + 40 * (d - date(2021, 1, 1)).days
                     for d in (von + timedelta(days=i) for i in range((bis - von).days + 1)) if d.weekday() < 5}
            return _pihps_antwort(werte)
        if "fpma" in url:
            return {"datapoints": [{"date": "2022-01-01", "price_value": 20000.0}]}
        raise AssertionError(url)

    def falscher_text(url, params=None, kopf=None):
        raise netz.AbrufFehler("MPOB nicht erreichbar")

    monkeypatch.setattr(netz, "hole_json", falsches_json)
    monkeypatch.setattr(netz, "hole_text", falscher_text)
    monkeypatch.setattr(inlandspreise.time, "sleep", lambda s: None)
    assert inlandspreise.main(["--heute", heute.isoformat()]) == 0
    e = speicher.lies_json(konfig.DATEN / "inlandspreise.json")
    lose = e["reihen"]["speiseoel_id_lose"]
    assert lose["status"] == "ok" and lose["urteil"] in ("Frühzeichen", "starkes Frühzeichen")
    assert "speiseoel_id_lose" in e["fruehzeichen"]
    assert e["reihen"]["cpo_my_tag"]["status"] == "Fehler"
    # Erstabruf in Jahresstücken ab 2018
    starts = [p["start_date"] for u, p in abrufe if "hargapangan" in u and p["comcat_id"] == "com_17"]
    assert starts[0] == "2018-01-01" and len(starts) == 5
    status = (konfig.ABGABE / "status-inlandspreise.md").read_text(encoding="utf-8")
    assert "Zustand: Warnung" in status
    # Zweiter Lauf holt nur noch die letzten dreißig Tage
    abrufe.clear()
    inlandspreise.main(["--heute", (heute + timedelta(days=1)).isoformat()])
    starts = [p["start_date"] for u, p in abrufe if "hargapangan" in u and p["comcat_id"] == "com_17"]
    assert starts == ["2022-01-30"]


def test_vorlesetext_nennt_das_fruehzeichen(ablage, netz_mit):
    s = szenario_rot()
    netz_mit(s)
    assert lauf.klimatologie.main(["--pro-minute", "0"]) == 0
    speicher.schreibe_json(konfig.DATEN / "inlandspreise.json", {
        "datum": s.heute.isoformat(), "reihen": {
            "speiseoel_id_lose": {"rohstoff": "palmoel", "name": "Speiseöl lose in Indonesien", "land": "Indonesien",
                                  "rolle": "fruehzeichen", "status": "ok", "urteil": "Frühzeichen", "art": "täglich",
                                  "veraenderung": 0.14, "letzter": {"datum": s.heute.isoformat(), "wert": 17000}},
            "pflanzenoel_id_monat": {"rohstoff": "palmoel", "name": "Pflanzenöl in Indonesien", "land": "Indonesien",
                                     "rolle": "ersatz", "status": "ok", "urteil": "ruhig", "art": "monatlich",
                                     "veraenderung": 0.02, "letzter": {"datum": "2027-06-01", "wert": 20000}},
        }})
    stand = lauf.lauf(s.heute, pro_minute=0)
    assert stand["rohstoffe"]["palmoel"]["inlandspreise"]["reihen"]
    gesamt = " ".join(p.read_text(encoding="utf-8") for p in sorted(konfig.ABGABE.glob("anlage-teil-*.md")))
    assert "Speiseöl lose in Indonesien: im Mittel der letzten vier Wochen vierzehn Prozent gestiegen" in gesamt
    assert "Das ist ein Frühzeichen" in gesamt and "Die Ampel ändert es nicht." in gesamt
    assert "Pflanzenöl in Indonesien" not in gesamt                      # Ersatz nur, wenn die Tagesreihe fehlt
    for teil in sorted(konfig.ABGABE.glob("anlage-teil-*.md")):
        text = teil.read_text(encoding="utf-8").split("\n", 2)[2]
        assert len(teil.read_text(encoding="utf-8")) <= vorlesen.GRENZE
        assert not re.search(r"\d", text)
