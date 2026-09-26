"""Täglicher Datenlauf des Metall-Agenten.

Schreibt daten/metall/<land>/stand.json, rueckblick.json, stoerungen.json, das Regen-Normal
der Wasserkraft-Standorte (klima/) und das Kursarchiv (kurse/), dazu den Vorlesetext
abgabe/metall-<land>-teil-N.md und abgabe/status-metall-<land>.md.

Aufruf: python -m anlage.metall [--land china] [--heute JJJJ-MM-TT] [--budget-minuten 25]
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta

from .. import __version__, konfig, speicher
from ..netz import AbrufFehler
from ..quellen import kurse, openmeteo
from . import quellen as q
from . import rechnen

HINWEIS = "Denkhilfe, keine Anlageberatung. Rot setzt nur der Metall-Wächter in der Cloud."
NORMAL_JAHRE = range(1991, 2021)


def lade(land: str) -> dict:
    return konfig.lade_yaml(konfig.KONFIG / "metalle" / f"{land}.yaml")


def ordner(land: str):
    return konfig.DATEN / "metall" / land


def _fehler(f: Exception) -> str:
    return f"{type(f).__name__}: {f}"[:300]


# ------------------------------------------------------------------ Kanäle
def _gegenseite(k, url, heute, alt, status):
    g = k["gegenseite"]
    ab = heute - timedelta(days=g["tage"])
    treffer, fehler = {}, []
    for begriff in g["begriffe"]:
        try:
            treffer[begriff] = q.hole_bundesregister(url, begriff, ab)
        except AbrufFehler as f:
            fehler.append(f"{begriff}: {_fehler(f)}")
    alte = ((alt or {}).get("gegenseite") or {}).get("dokumente") or []
    if not treffer:
        status["bundesregister"] = {"status": "Fehler", "meldung": "; ".join(fehler)[:300]}
        grenze = ab.isoformat()
        return [{**d, "neu": False} for d in alte if (d.get("datum") or "") >= grenze], "letzter Stand"
    status["bundesregister"] = {"status": "Warnung" if fehler else "ok",
                                "meldung": "; ".join(fehler)[:300] if fehler else None}
    bekannt = {d["nummer"] for d in alte} if alt else None
    return rechnen.gegenseite(treffer, g, bekannt), "frisch"


def _erdbeben(k, url, heute, status):
    s = k["stoerung"]
    try:
        beben = q.hole_erdbeben(url, heute - timedelta(days=s["gelb_tage"]), min(st["ab"] for st in s["erdbeben"]),
                                q.suchrechteck(k["standorte"]))
    except AbrufFehler as f:
        status["usgs_beben"] = {"status": "Fehler", "meldung": _fehler(f)}
        return [], 0
    status["usgs_beben"] = {"status": "ok", "meldung": None}
    return rechnen.erdbeben_treffer(beben, k["standorte"], s["erdbeben"]), len(beben)


def _regen(k, url, heute, protokoll_alt, status):
    s = k["stoerung"]
    try:
        regen = q.hole_vorhersage(url, k["standorte"])
    except AbrufFehler as f:
        status["openmeteo_vorhersage"] = {"status": "Fehler", "meldung": _fehler(f)}
        return rechnen.fuehre_stoerungen(protokoll_alt, [], heute, s["gelb_tage"]), [], None
    status["openmeteo_vorhersage"] = {"status": "ok", "meldung": None}
    treffer = rechnen.starkregen(regen, k["standorte"], heute, s["starkregen_ab_mm"])
    gemessen = [t for t in treffer if t["art"] == "gemessen"]
    voraus = [t for t in treffer if t["art"] == "vorhergesagt"]
    hoechst = {kennung: max((w for w in tage.values() if w is not None), default=None) for kennung, tage in regen.items()}
    return rechnen.fuehre_stoerungen(protokoll_alt, gemessen, heute, s["gelb_tage"]), voraus, hoechst


def _trocken(k, om, heute, o, frist, status):
    """Regen-Normal 1991–2020 der Wasserkraft-Standorte einmalig laden (jahrweise, im Zeitbudget),
    dann die letzten neunzig Tage dagegen stellen."""
    s = k["stoerung"]
    ergebnis, fehler = {}, []
    for st in (x for x in k["standorte"] if x.get("wasserkraft")):
        pfad = o / "klima" / f"{st['kennung']}.json"
        klima = speicher.lies_json(pfad, {}) or {}
        for jahr in NORMAL_JAHRE:
            if jahr in (klima.get("jahre_fertig") or []):
                continue
            if time.monotonic() > frist:
                break
            try:
                tage = openmeteo.hole_tage(om["url"], st, date(jahr, 1, 1), date(jahr, 12, 31), modell=om.get("modell"))
            except AbrufFehler as f:
                fehler.append(f"{st['name']} {jahr}: {_fehler(f)}")
                break
            rechnen.klima_ergaenzen(klima, jahr, tage)
            speicher.schreibe_json(pfad, klima, kompakt=True)
            openmeteo.drossel(openmeteo.gewicht(365), om.get("gewicht_pro_minute", 75))
        fertig = len(klima.get("jahre_fertig") or [])
        if fertig < len(NORMAL_JAHRE):
            ergebnis[st["kennung"]] = {"urteil": "Normal wird geladen", "jahre": fertig, "von": len(NORMAL_JAHRE)}
            continue
        try:
            ist = openmeteo.hole_tage(om["url"], st, heute - timedelta(days=s["trocken_fenster_tage"] + 12),
                                      heute - timedelta(days=1), modell=om.get("modell"))
        except AbrufFehler as f:
            fehler.append(f"{st['name']} aktuell: {_fehler(f)}")
            ergebnis[st["kennung"]] = {"urteil": "nicht abrufbar"}
            continue
        ergebnis[st["kennung"]] = rechnen.trockenheit(ist, klima, s["trocken_fenster_tage"], s["trocken_unter"],
                                                      s["trocken_normal_ab_mm"])
    status["openmeteo"] = {"status": "Warnung" if fehler else "ok", "meldung": "; ".join(fehler)[:300] if fehler else None}
    return ergebnis


def _kurse(k, o, holen, status):
    ab = rechnen.tag(k["rueckblick"].get("kurse_ab") or "2008-01-01").isoformat()
    ticker = [i["ticker"] for i in k["instrumente"]] + [k["vergleich"]["ticker"]]
    reihen, fehler = {}, []
    for t in ticker:
        pfad = kurse.archiv_pfad(o / "kurse", t)
        try:
            neu = [e for e in holen(t, "max") if e["datum"] >= ab]
            reihen[t] = kurse.ergaenze_archiv(pfad, neu)
        except Exception as f:  # ein Wert darf die anderen nicht mitreißen
            fehler.append(f"{t}: {_fehler(f)}")
            reihen[t] = kurse.lies_archiv(pfad)
    if fehler:
        status["yahoo"] = {"status": "Fehler" if len(fehler) == len(ticker) else "Warnung",
                           "meldung": "; ".join(fehler)[:300]}
    else:
        status["yahoo"] = {"status": "ok", "meldung": None}
    return reihen


# ------------------------------------------------------------------ Lauf
def lauf(land: str, heute: date, zeitpunkt: datetime, budget_minuten: float = 25,
         holen=None) -> dict:
    holen = holen or kurse.hole_yahoo
    frist = time.monotonic() + budget_minuten * 60
    k = lade(land)
    quellen_konfig = konfig.lade_yaml(konfig.KONFIG / "quellen.yaml")
    o = ordner(land)
    alt = speicher.lies_json(o / "stand.json", None)
    status: dict[str, dict] = {}

    fristen = rechnen.fristen(k.get("fristen") or [], heute, k["fristen_gelb_ab_tage"])
    dokumente, herkunft = _gegenseite(k, quellen_konfig["bundesregister"]["url"], heute, alt, status)
    beben, beben_alle = _erdbeben(k, quellen_konfig["usgs_beben"]["url"], heute, status)
    protokoll_alt = speicher.lies_json(o / "stoerungen.json", []) or []
    protokoll, voraus, hoechst = _regen(k, quellen_konfig["openmeteo_vorhersage"]["url"], heute, protokoll_alt, status)
    speicher.schreibe_json(o / "stoerungen.json", protokoll)
    trocken = _trocken(k, quellen_konfig["openmeteo"], heute, o, frist, status)
    reihen = _kurse(k, o, holen, status)

    vergleich = reihen.get(k["vergleich"]["ticker"]) or []
    preise = {}
    for i in k["instrumente"]:
        preise[i["ticker"]] = {"name": i["name"], "achse": i["achse"], "rolle": i["rolle"], "hinweis": i.get("hinweis"),
                               **rechnen.preisprobe(reihen.get(i["ticker"]) or [], vergleich, k["preisprobe"], heute)}
    rueck = rechnen.rueckblick(k["ereignisse"], k["instrumente"], reihen, k["vergleich"]["ticker"], k["rueckblick"])
    speicher.schreibe_json(o / "rueckblick.json", {"stand": zeitpunkt.isoformat(timespec="seconds"),
                                                   "vergleich": k["vergleich"], "regeln": k["rueckblick"],
                                                   "werte": rueck})

    achsen = rechnen.grundstufe(k, heute, fristen, dokumente, beben, protokoll, voraus, trocken)
    for a, eintrag in achsen.items():
        eintrag["instrumente"] = [t for t, p in preise.items() if p["achse"] == a]
    wechsel = []
    for a, eintrag in achsen.items():
        vorher = (((alt or {}).get("achsen") or {}).get(a) or {}).get("stufe")
        if vorher and vorher != eintrag["stufe"]:
            wechsel.append({"achse": a, "vorher": vorher, "jetzt": eintrag["stufe"]})

    zustaende = [s["status"] for s in status.values()]
    zustand = ("Fehler" if zustaende and all(z == "Fehler" for z in zustaende)
               else "Warnung" if any(z != "ok" for z in zustaende) else "in Ordnung")
    namen = {kennung: quellen_konfig[kennung]["name"] for kennung in status}
    stand = {
        "stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "version": __version__,
        "land": k["kennung"], "name": k["name"], "laenderpaar": k.get("laenderpaar"), "rolle": k["rolle"],
        "hinweis": HINWEIS, "zustand": zustand,
        "reihenfolge": rechnen.reihenfolge(achsen), "achsen": achsen, "wechsel": wechsel,
        "fristen": fristen,
        "gegenseite": {"herkunft": herkunft, "tage": k["gegenseite"]["tage"], "dokumente": dokumente},
        "stoerung": {"erdbeben": beben, "erdbeben_gesamt": beben_alle, "starkregen_gemessen": protokoll,
                     "starkregen_vorhergesagt": voraus, "regen_hoechst_mm": hoechst, "trocken": trocken,
                     "gelb_tage": k["stoerung"]["gelb_tage"]},
        "preise": preise, "vergleich": k["vergleich"],
        "rueckblick": {t: {kk: v for kk, v in r.items() if kk != "faelle"} for t, r in rueck.items()},
        "standorte": {s["kennung"]: s["name"] for s in k["standorte"]},
        "quellen": {kennung: {"name": namen[kennung], **s} for kennung, s in status.items()},
    }
    speicher.schreibe_json(o / "stand.json", stand)
    return stand


def main(argv: list[str] | None = None) -> int:
    from ..ausgabe import metall_text

    teiler = argparse.ArgumentParser(description="Datenlauf des Metall-Agenten")
    teiler.add_argument("--land", default="china")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    teiler.add_argument("--budget-minuten", type=float, default=25)
    args = teiler.parse_args(argv)
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    stand = lauf(args.land, zeitpunkt.date(), zeitpunkt, args.budget_minuten)
    metall_text.schreibe(stand, konfig.ABGABE)
    print(metall_text.zusammenfassung(stand))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
