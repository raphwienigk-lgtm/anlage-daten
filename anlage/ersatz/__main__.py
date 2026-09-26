"""Täglicher Lauf eines Ersatz-Sensors (erster Fall: Haselnuss → Select Harvests).

Schreibt daten/ersatz/<kennung>/stand.json, saisons.json (Tagesminima der Frostsaisons ab 1991,
einmalig im Zeitbudget geladen), rueckblick.json, das Kursarchiv (kurse/), dazu
abgabe/ersatz-<kennung>-teil-N.md und abgabe/status-ersatz-<kennung>.md.

Aufruf: python -m anlage.ersatz [--kennung haselnuss] [--heute JJJJ-MM-TT] [--budget-minuten 20]
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta

from .. import __version__, konfig, speicher
from ..metall import rechnen as mr
from ..netz import AbrufFehler
from ..quellen import kurse, openmeteo
from . import frost

HINWEIS = "Denkhilfe, keine Anlageberatung. Der Sensor schlägt beim Original aus, gekauft würde der Ersatz."
ERA5_VERZUG_TAGE = 6


def lade(kennung: str) -> dict:
    return konfig.lade_yaml(konfig.KONFIG / "ersatz" / f"{kennung}.yaml")


def ordner(kennung: str):
    return konfig.DATEN / "ersatz" / kennung


def _fehler(f: Exception) -> str:
    return f"{type(f).__name__}: {f}"[:300]


def _hoehe(st: dict, s: dict) -> float:
    return st.get("hoehe_m", s.get("hoehe_m"))


# ------------------------------------------------------------------ Abrufe
def lies_minima(antwort) -> dict[str, float | None]:
    if not isinstance(antwort, dict) or antwort.get("error"):
        raise AbrufFehler(f"Open-Meteo meldet: {antwort.get('reason') if isinstance(antwort, dict) else antwort}")
    taeglich = antwort.get("daily") or {}
    tage, werte = taeglich.get("time") or [], taeglich.get("temperature_2m_min") or []
    if not tage or len(tage) != len(werte):
        raise AbrufFehler("Open-Meteo lieferte keine Tagesminima")
    return dict(zip(tage, werte))


def hole_minima(url: str, st: dict, s: dict, von: date, bis: date, modell: str | None) -> dict:
    params = {"latitude": st["lat"], "longitude": st["lon"], "elevation": _hoehe(st, s),
              "start_date": von.isoformat(), "end_date": bis.isoformat(),
              "daily": "temperature_2m_min", "timezone": "Europe/Istanbul"}
    if modell:
        params["models"] = modell
    return lies_minima(openmeteo._hole(url, params))


def hole_vorhersage(url: str, s: dict) -> dict[str, dict]:
    orte = s["standorte"]
    params = {"latitude": ",".join(str(o["lat"]) for o in orte), "longitude": ",".join(str(o["lon"]) for o in orte),
              "elevation": ",".join(str(_hoehe(o, s)) for o in orte), "daily": "temperature_2m_min",
              "past_days": 5, "forecast_days": s.get("vorhersage_tage", 10), "timezone": "Europe/Istanbul"}
    from .. import netz
    antwort = netz.hole_json(url, params)
    if isinstance(antwort, dict) and antwort.get("error"):
        raise AbrufFehler(f"Open-Meteo-Vorhersage meldet: {antwort.get('reason')}")
    liste = antwort if isinstance(antwort, list) else [antwort]
    if len(liste) != len(orte):
        raise AbrufFehler(f"Open-Meteo-Vorhersage: {len(liste)} Antworten für {len(orte)} Orte")
    return {o["kennung"]: lies_minima(a) for o, a in zip(orte, liste)}


# ------------------------------------------------------------------ Saisons ab 1991
def letzte_fertige_saison(heute: date, s: dict) -> int:
    _, bis = frost.saison_grenzen(heute.year, s["saison"])
    return heute.year if heute > bis + timedelta(days=ERA5_VERZUG_TAGE) else heute.year - 1


def lade_saisons(k: dict, om: dict, heute: date, o, frist: float, status: dict) -> dict:
    s = k["sensor"]
    pfad = o / "saisons.json"
    daten = speicher.lies_json(pfad, {}) or {}
    werte, fertig = daten.setdefault("werte", {}), daten.setdefault("fertig", {})
    letzte = letzte_fertige_saison(heute, s)
    fehler = []
    for jahr in range(k["rueckblick"]["jahre_ab"], letzte + 1):
        for st in s["standorte"]:
            if jahr in (fertig.get(st["kennung"]) or []):
                continue
            if time.monotonic() > frist:
                break
            von, bis = frost.saison_grenzen(jahr, s["saison"])
            try:
                neu = hole_minima(om["url"], st, s, von, bis, om.get("modell"))
            except AbrufFehler as f:
                fehler.append(f"{st['name']} {jahr}: {_fehler(f)}")
                continue
            werte.setdefault(st["kennung"], {}).update({d: w for d, w in neu.items() if w is not None})
            fertig.setdefault(st["kennung"], []).append(jahr)
            speicher.schreibe_json(pfad, daten, kompakt=True)
            openmeteo.drossel(openmeteo.gewicht((bis - von).days + 1), om.get("gewicht_pro_minute", 75))
        if len(fehler) >= 3:
            break
    jahre = range(k["rueckblick"]["jahre_ab"], letzte + 1)
    vollstaendig = [j for j in jahre if all(j in (fertig.get(st["kennung"]) or []) for st in s["standorte"])]
    status["saisons"] = {"geladen": len(vollstaendig), "von": len(jahre), "fehler": fehler[:5]}
    return {"werte": werte, "jahre": vollstaendig}


# ------------------------------------------------------------------ Lauf
def lauf(kennung: str, heute: date, zeitpunkt: datetime, budget_minuten: float = 20, holen=None) -> dict:
    holen = holen or kurse.hole_yahoo
    frist = time.monotonic() + budget_minuten * 60
    k = lade(kennung)
    s = k["sensor"]
    q = konfig.lade_yaml(konfig.KONFIG / "quellen.yaml")
    om = q["openmeteo"]
    o = ordner(kennung)
    alt = speicher.lies_json(o / "stand.json", None)
    status: dict[str, dict] = {}

    # Saisons ab 1991 und Abgleich mit den belegten Frostjahren
    hist = lade_saisons(k, om, heute, o, frist, status)
    saisons = [frost.saison_urteil(hist["werte"], j, s) for j in hist["jahre"]]
    abgleich = frost.abgleich(saisons, k.get("bekannte_frostjahre") or [])
    status["openmeteo"] = {"status": "Warnung" if status["saisons"]["fehler"] else "ok",
                           "meldung": "; ".join(status["saisons"]["fehler"])[:300] or None}

    # laufende Saison: gemessen (ERA5) und vorhergesagt
    ph = frost.phase(heute, s)
    von, bis = frost.saison_grenzen(heute.year, s["saison"])
    gemessen, vorhergesagt, aktuell_tiefste = [], [], None
    if ph != "außer Saison" or von <= heute <= bis + timedelta(days=ERA5_VERZUG_TAGE):
        if heute > von:
            werte = {}
            for st in s["standorte"]:
                try:
                    werte[st["kennung"]] = hole_minima(om["url"], st, s, von, min(bis, heute - timedelta(days=1)),
                                                       om.get("modell"))
                except AbrufFehler as f:
                    status["openmeteo"] = {"status": "Warnung", "meldung": _fehler(f)}
            gemessen = frost.naechte(werte, s["schwelle_c"], s["stark_c"], s["mindest_standorte"], von, bis)
            aktuell_tiefste = frost.tiefste(werte, von, bis)
        if ph != "außer Saison":
            try:
                vh = hole_vorhersage(q["openmeteo_vorhersage"]["url"], s)
                status["openmeteo_vorhersage"] = {"status": "ok", "meldung": None}
                vorhergesagt = [n for n in frost.naechte(vh, s["schwelle_c"], s["stark_c"], s["mindest_standorte"])
                                if n["datum"] >= heute.isoformat()]
            except AbrufFehler as f:
                status["openmeteo_vorhersage"] = {"status": "Fehler", "meldung": _fehler(f)}

    # Kurse, Preisprobe, Ereignis-Rückblick
    ab = mr.tag(k["rueckblick"].get("kurse_ab") or "2000-01-01").isoformat()
    reihen, kursfehler = {}, []
    ticker = [e["ticker"] for e in k["ersatz"]] + [k["vergleich"]["ticker"]]
    for t in ticker:
        pfad = kurse.archiv_pfad(o / "kurse", t)
        try:
            reihen[t] = kurse.ergaenze_archiv(pfad, [e for e in holen(t, "max") if e["datum"] >= ab])
        except Exception as f:  # ein Wert darf die anderen nicht mitreißen
            kursfehler.append(f"{t}: {_fehler(f)}")
            reihen[t] = kurse.lies_archiv(pfad)
    status["yahoo"] = ({"status": "ok", "meldung": None} if not kursfehler else
                       {"status": "Fehler" if len(kursfehler) == len(ticker) else "Warnung",
                        "meldung": "; ".join(kursfehler)[:300]})
    vergleich = reihen.get(k["vergleich"]["ticker"]) or []
    preise = {e["ticker"]: {"name": e["name"], "rolle": e.get("rolle"), "hinweis": e.get("hinweis"),
                            "waehrung": e.get("waehrung", "USD"),
                            **mr.preisprobe(reihen.get(e["ticker"]) or [], vergleich, k["preisprobe"], heute)}
              for e in k["ersatz"]}
    ereignisse = [{"datum": (date.fromisoformat(x["erste"]) + timedelta(days=1)).isoformat(), "jahr": x["jahr"],
                   "urteil": x["urteil"]} for x in saisons if x["erste"]]
    rueck = rueckblick(ereignisse, k, reihen)
    speicher.schreibe_json(o / "rueckblick.json", {"stand": zeitpunkt.isoformat(timespec="seconds"),
                                                   "regeln": k["rueckblick"], "werte": rueck})

    # Stufe
    saison_jetzt = next((x for x in saisons if x["jahr"] == heute.year), None)
    stufe, gruende = stufe_bestimmen(ph, gemessen, vorhergesagt, rueck, preise, heute, saison_jetzt)
    vorher = (alt or {}).get("stufe")
    zustaende = [x["status"] for x in status.values() if isinstance(x, dict) and "status" in x]
    zustand = ("Fehler" if zustaende and all(z == "Fehler" for z in zustaende)
               else "Warnung" if any(z != "ok" for z in zustaende) else "in Ordnung")
    stand = {
        "stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "version": __version__,
        "kennung": k["kennung"], "name": k["name"], "rolle": k["rolle"], "hinweis": HINWEIS,
        "original": k.get("original"), "ersatz": k["ersatz"], "vergleich": k["vergleich"],
        "phase": ph, "saison": {"von": von.isoformat(), "bis": bis.isoformat(),
                                "vorwarnung_ab": (von - timedelta(days=s.get("vorwarnung_tage", 0))).isoformat()},
        "schwellen": {"frost_c": s["schwelle_c"], "stark_c": s["stark_c"], "mindest_standorte": s["mindest_standorte"],
                      "hoehe_m": s["hoehe_m"]},
        "standorte": {st["kennung"]: st["name"] for st in s["standorte"]},
        "stufe": stufe, "gruende": gruende,
        "wechsel": {"vorher": vorher, "jetzt": stufe} if vorher and vorher != stufe else None,
        "aktuell": {"gemessen": gemessen, "vorhergesagt": vorhergesagt, "tiefste": aktuell_tiefste},
        "letzte_saison": saisons[-1] if saisons else None,
        "saisons": saisons, "abgleich": abgleich, "saisons_geladen": status["saisons"],
        "preise": preise, "rueckblick": {t: {kk: v for kk, v in r.items() if kk != "faelle"} for t, r in rueck.items()},
        "zustand": zustand,
        "quellen": {kk: v for kk, v in status.items() if kk != "saisons"},
    }
    speicher.schreibe_json(o / "stand.json", stand)
    return stand


def rueckblick(ereignisse: list[dict], k: dict, reihen: dict[str, list[dict]]) -> dict:
    """Wie lief der Ersatz nach den Spätfrost-Jahren gegen den Vergleichsmaßstab?"""
    r = k["rueckblick"]
    horizonte, haupt = r["horizonte"], r["haupt"]
    ref_reihe = reihen.get(k["vergleich"]["ticker"]) or []
    ergebnis = {}
    for e in k["ersatz"]:
        reihe = reihen.get(e["ticker"]) or []
        faelle = []
        for x in ereignisse:
            d = date.fromisoformat(x["datum"])
            eigen = mr.ereignis_renditen(reihe, d, horizonte, r["vorlauf"])
            if eigen is None:
                continue
            ref = mr.ereignis_renditen(ref_reihe, d, horizonte, r["vorlauf"])
            fall = {**x, **eigen}
            for h in horizonte:
                fall[f"v{h}"] = mr._vorsprung(eigen, ref, f"r{h}")
            fall["v_vorlauf"] = mr._vorsprung(eigen, ref, "vorlauf")
            if fall.get(f"v{haupt}") is not None:
                fall["treffer"] = fall[f"v{haupt}"] >= r["treffer_ab"]
            faelle.append(fall)
        zusammen = mr._zusammenfassen(faelle, horizonte, haupt)
        b = r["bestanden"]
        if zusammen["n"] < b["mindestens"]:
            urteil = "zu wenige Fälle"
        elif zusammen["trefferquote"] >= b["trefferquote"] and (zusammen.get(f"v{haupt}") or 0) > 0:
            urteil = "bestanden"
        else:
            urteil = "nicht bestanden"
        ergebnis[e["ticker"]] = {"name": e["name"], "rolle": e.get("rolle"), "erster_kurs": reihe[0]["datum"] if reihe else None,
                                 "urteil": urteil, "haupt": haupt, "zusammen": zusammen, "faelle": faelle}
    return ergebnis


def stufe_bestimmen(ph: str, gemessen: list[dict], vorhergesagt: list[dict], rueck: dict, preise: dict,
                    heute: date | None = None, saison_jetzt: dict | None = None) -> tuple[str, list[dict]]:
    """Grün außer Saison oder ohne Frost; Gelb bei vorhergesagtem oder gemessenem Frost und nach einem
    Frostjahr bis zum Ende der Ernte (30. September); Rot nur bei gemessenem starkem Frost, bestandenem
    Rückblick und schlafendem Markt."""
    gruende = []
    if ph == "außer Saison" and not gemessen:
        if (saison_jetzt and saison_jetzt["urteil"] != "ruhig" and heute
                and heute <= date(saison_jetzt["jahr"], 9, 30)):
            return "Gelb", [{"art": "frostjahr", "jahr": saison_jetzt["jahr"], "urteil": saison_jetzt["urteil"],
                             "naechte": saison_jetzt["frostnaechte"], "tiefste": saison_jetzt["tiefste"]}]
        return "Grün", [{"art": "außer Saison"}]
    if vorhergesagt:
        gruende.append({"art": "vorhergesagt", "datum": vorhergesagt[0]["datum"], "orte": vorhergesagt[0]["orte"],
                        "tiefste": min(n["tiefste"] for n in vorhergesagt), "naechte": len(vorhergesagt)})
    if gemessen:
        stark = [n for n in gemessen if n["stark"]]
        gruende.append({"art": "gemessen", "datum": gemessen[0]["datum"], "naechte": len(gemessen),
                        "stark": bool(stark), "tiefste": min(n["tiefste"] for n in gemessen)})
        if stark:
            bestanden = [t for t, r in rueck.items() if r["urteil"] == "bestanden" and (preise.get(t) or {}).get("markt_schlaeft")]
            if bestanden:
                return "Rot", gruende
            gruende.append({"art": "rot_gesperrt",
                            "grund": "Rückblick nicht bestanden" if not any(r["urteil"] == "bestanden" for r in rueck.values())
                            else "Kurs schon gelaufen"})
    return ("Gelb" if gruende else "Grün"), gruende


def main(argv: list[str] | None = None) -> int:
    from ..ausgabe import ersatz_text

    teiler = argparse.ArgumentParser(description="Ersatz-Sensor")
    teiler.add_argument("--kennung", default="haselnuss")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    teiler.add_argument("--budget-minuten", type=float, default=20)
    args = teiler.parse_args(argv)
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    stand = lauf(args.kennung, zeitpunkt.date(), zeitpunkt, args.budget_minuten)
    ersatz_text.schreibe(stand, konfig.ABGABE)
    print(ersatz_text.zusammenfassung(stand))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
