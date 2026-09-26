"""Täglicher Lauf der Ersatz-Sensoren: Haselnuss → Select Harvests (Spätfrost) und
Palladium → Platin (Preis des Originals).

Schreibt je Kennung daten/ersatz/<kennung>/stand.json, rueckblick.json, verlauf.jsonl, schattendepot.json,
das Kursarchiv (kurse/), beim Frost-Sensor saisons.json (Tagesminima der Frostsaisons ab 1991, einmalig
im Zeitbudget geladen), dazu abgabe/ersatz-<kennung>-teil-N.md und abgabe/status-ersatz-<kennung>.md.

Aufruf: python -m anlage.ersatz [--kennung haselnuss|palladium|alle] [--heute JJJJ-MM-TT] [--budget-minuten 20]
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta

from .. import __version__, konfig, speicher
from ..metall import rechnen as mr
from ..netz import AbrufFehler
from ..quellen import kurse, openmeteo
from . import frost, preis

HINWEIS = "Denkhilfe, keine Anlageberatung. Der Sensor schlägt beim Original aus, gekauft würde der Ersatz."
ERA5_VERZUG_TAGE = 6
ARCHIV_TIMEOUT = 90       # Sekunden; das Archiv antwortet von GitHub aus manchmal erst nach einer Minute


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


def hole_minima_mehrere(url: str, orte: list[dict], s: dict, von: date, bis: date, modell: str | None) -> dict[str, dict]:
    """Eine Saison für mehrere Orte in einem Abruf (Open-Meteo nimmt Listen). Von GitHub aus antwortet das
    Archiv oft langsam; ein Abruf je Saison statt je Ort und Saison spart die meiste Wartezeit."""
    params = {"latitude": ",".join(str(o["lat"]) for o in orte), "longitude": ",".join(str(o["lon"]) for o in orte),
              "elevation": ",".join(str(_hoehe(o, s)) for o in orte),
              "start_date": von.isoformat(), "end_date": bis.isoformat(),
              "daily": "temperature_2m_min", "timezone": "Europe/Istanbul"}
    if modell:
        params["models"] = modell
    antwort = openmeteo._hole(url, params, timeout=ARCHIV_TIMEOUT)
    liste = antwort if isinstance(antwort, list) else [antwort]
    if len(liste) != len(orte):
        raise AbrufFehler(f"Open-Meteo-Archiv: {len(liste)} Antworten für {len(orte)} Orte")
    return {o["kennung"]: lies_minima(a) for o, a in zip(orte, liste)}


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
        offen = [st for st in s["standorte"] if jahr not in (fertig.get(st["kennung"]) or [])]
        if not offen:
            continue
        if time.monotonic() > frist:
            break
        von, bis = frost.saison_grenzen(jahr, s["saison"])
        try:
            neu = hole_minima_mehrere(om["url"], offen, s, von, bis, om.get("modell"))
        except AbrufFehler as f:
            fehler.append(f"{jahr}: {_fehler(f)}")
            if len(fehler) >= 3:
                break
            continue
        for st in offen:
            werte.setdefault(st["kennung"], {}).update({d: w for d, w in neu[st["kennung"]].items() if w is not None})
            fertig.setdefault(st["kennung"], []).append(jahr)
        speicher.schreibe_json(pfad, daten, kompakt=True)
        openmeteo.drossel(openmeteo.gewicht((bis - von).days + 1) * len(offen), om.get("gewicht_pro_minute", 75))
    jahre = range(k["rueckblick"]["jahre_ab"], letzte + 1)
    vollstaendig = [j for j in jahre if all(j in (fertig.get(st["kennung"]) or []) for st in s["standorte"])]
    status["saisons"] = {"geladen": len(vollstaendig), "von": len(jahre), "fehler": fehler[:5]}
    return {"werte": werte, "jahre": vollstaendig}


# ------------------------------------------------------------------ Lauf
def _kurse(k: dict, o, holen, status: dict, weitere: list[str] | None = None) -> dict[str, list[dict]]:
    ab = mr.tag(k["rueckblick"].get("kurse_ab") or "2000-01-01").isoformat()
    reihen, kursfehler = {}, []
    ticker = (weitere or []) + [e["ticker"] for e in k["ersatz"]] + [k["vergleich"]["ticker"]]
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
    return reihen


def _preisproben(k: dict, reihen: dict, heute: date) -> dict:
    vergleich = reihen.get(k["vergleich"]["ticker"]) or []
    return {e["ticker"]: {"name": e["name"], "rolle": e.get("rolle"), "hinweis": e.get("hinweis"),
                          "waehrung": e.get("waehrung", "USD"),
                          **mr.preisprobe(reihen.get(e["ticker"]) or [], vergleich, k["preisprobe"], heute)}
            for e in k["ersatz"]}


def _zustand(status: dict) -> str:
    zustaende = [x["status"] for x in status.values() if isinstance(x, dict) and "status" in x]
    return ("Fehler" if zustaende and all(z == "Fehler" for z in zustaende)
            else "Warnung" if any(z != "ok" for z in zustaende) else "in Ordnung")


def lauf(kennung: str, heute: date, zeitpunkt: datetime, budget_minuten: float = 20, holen=None) -> dict:
    holen = holen or kurse.hole_yahoo
    k = lade(kennung)
    if k["sensor"]["art"] == "preisabstand":
        return lauf_preis(k, heute, zeitpunkt, holen)
    frist = time.monotonic() + budget_minuten * 60
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
            try:
                werte = hole_minima_mehrere(om["url"], s["standorte"], s, von, min(bis, heute - timedelta(days=1)),
                                            om.get("modell"))
            except AbrufFehler as f:
                werte = {}
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
    reihen = _kurse(k, o, holen, status)
    preise = _preisproben(k, reihen, heute)
    ereignisse = [{"datum": (date.fromisoformat(x["erste"]) + timedelta(days=1)).isoformat(), "jahr": x["jahr"],
                   "urteil": x["urteil"]} for x in saisons if x["erste"]]
    rueck = rueckblick(ereignisse, k, reihen)
    speicher.schreibe_json(o / "rueckblick.json", {"stand": zeitpunkt.isoformat(timespec="seconds"),
                                                   "regeln": k["rueckblick"], "werte": rueck})

    # Stufe
    saison_jetzt = next((x for x in saisons if x["jahr"] == heute.year), None)
    stufe, gruende = stufe_bestimmen(ph, gemessen, vorhergesagt, rueck, preise, heute, saison_jetzt)
    depot = schattendepot(o / "schattendepot.json", k, stufe, heute, zeitpunkt, reihen)
    vorher = (alt or {}).get("stufe")
    zustand = _zustand(status)
    stand = {
        "stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "version": __version__,
        "kennung": k["kennung"], "name": k["name"], "rolle": k["rolle"], "hinweis": HINWEIS, "sensor_art": s["art"],
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
        "schattendepot": depot,
        "zustand": zustand,
        "quellen": {kk: v for kk, v in status.items() if kk != "saisons"},
    }
    speicher.schreibe_json(o / "stand.json", stand)
    speicher.haenge_zeile_an(o / "verlauf.jsonl", {"zeit": stand["stand"], "datum": stand["datum"], "zustand": zustand,
                                                    "stufe": stufe, "phase": ph})
    return stand


def lauf_preis(k: dict, heute: date, zeitpunkt: datetime, holen) -> dict:
    """Preis-Sensor: Signale am Original (Sprung, Verhältnis), Rückblick und Preisprobe am Ersatz."""
    s = k["sensor"]
    o = ordner(k["kennung"])
    alt = speicher.lies_json(o / "stand.json", None)
    status: dict[str, dict] = {}
    reihen = _kurse(k, o, holen, status, [s["original_ticker"]])
    original = reihen.get(s["original_ticker"]) or []
    ersatz_reihe = reihen.get(k["ersatz"][0]["ticker"]) or []
    liste = preis.signale(original, ersatz_reihe, s)
    jetzt = preis.lage(original, ersatz_reihe, s)
    preise = _preisproben(k, reihen, heute)
    # Ereignistag ist der Tag nach dem Signal: gekauft werden kann erst nach dem Schlusskurs, der es auslöst.
    ereignisse = [{"datum": (date.fromisoformat(x["datum"]) + timedelta(days=1)).isoformat(), "jahr": int(x["datum"][:4]),
                   "art": x["art"], "signal": x["datum"]} for x in liste]
    rueck = rueckblick(ereignisse, k, reihen)
    speicher.schreibe_json(o / "rueckblick.json", {"stand": zeitpunkt.isoformat(timespec="seconds"),
                                                   "regeln": k["rueckblick"], "werte": rueck})
    stufe, gruende = stufe_preis(liste, jetzt, rueck, preise, heute, s)
    depot = schattendepot(o / "schattendepot.json", k, stufe, heute, zeitpunkt, reihen)
    vorher = (alt or {}).get("stufe")
    zustand = _zustand(status) if original else "Fehler"
    stand = {
        "stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "version": __version__,
        "kennung": k["kennung"], "name": k["name"], "rolle": k["rolle"], "hinweis": HINWEIS, "sensor_art": s["art"],
        "original": {**(k.get("original") or {}), "ticker": s["original_ticker"]}, "ersatz": k["ersatz"],
        "vergleich": k["vergleich"], "ersatz_name": s.get("ersatz_name"), "phase": "ganzjährig",
        "schwellen": {x: s[x] for x in ("anstieg_tage", "anstieg_ab", "verhaeltnis_ab", "pause_tage", "gelb_tage", "rot_tage")},
        "stufe": stufe, "gruende": gruende,
        "wechsel": {"vorher": vorher, "jetzt": stufe} if vorher and vorher != stufe else None,
        "lage": jetzt, "signale": liste, "erster_kurs": original[0]["datum"] if original else None,
        "preise": preise, "rueckblick": {t: {kk: v for kk, v in r.items() if kk != "faelle"} for t, r in rueck.items()},
        "schattendepot": depot, "zustand": zustand, "quellen": status,
    }
    speicher.schreibe_json(o / "stand.json", stand)
    speicher.haenge_zeile_an(o / "verlauf.jsonl", {"zeit": stand["stand"], "datum": stand["datum"], "zustand": zustand,
                                                    "stufe": stufe, "phase": "ganzjährig"})
    return stand


def stufe_preis(signale: list[dict], jetzt: dict, rueck: dict, preise: dict, heute: date, s: dict) -> tuple[str, list[dict]]:
    """Gelb, solange ein Signal jünger als `gelb_tage` ist oder das Original teurer ist als der Ersatz;
    Rot nur bei einem frischen Signal, bestandenem Rückblick und schlafendem Markt."""
    gruende = []
    frisch = [x for x in signale if (heute - date.fromisoformat(x["datum"])).days <= s["gelb_tage"]]
    if frisch:
        x = frisch[-1]
        gruende.append({"art": "signal", "art_signal": x["art"], "datum": x["datum"], "wert": x["wert"],
                        "verhaeltnis": x.get("verhaeltnis"), "anzahl": len(frisch)})
    if jetzt.get("verhaeltnis") is not None and jetzt["verhaeltnis"] >= s["verhaeltnis_ab"]:
        gruende.append({"art": "teurer", "verhaeltnis": jetzt["verhaeltnis"]})
    if not gruende:
        return "Grün", [{"art": "ruhig", "anstieg": jetzt.get("anstieg"), "verhaeltnis": jetzt.get("verhaeltnis")}]
    if frisch and (heute - date.fromisoformat(frisch[-1]["datum"])).days <= s["rot_tage"]:
        if any(r["urteil"] == "bestanden" and (preise.get(t) or {}).get("markt_schlaeft") for t, r in rueck.items()):
            return "Rot", gruende
        gruende.append({"art": "rot_gesperrt",
                        "grund": "Rückblick nicht bestanden" if not any(r["urteil"] == "bestanden" for r in rueck.values())
                        else "Kurs schon gelaufen"})
    return "Gelb", gruende


def schattendepot(pfad, k: dict, stufe: str, heute: date, zeitpunkt: datetime, reihen: dict[str, list[dict]]) -> dict:
    """Rot eröffnet einen gedachten Kauf des Ersatzes, wenn keiner offen ist. Geschlossen wird nach der
    geltenden Ausstiegsregel aus dem Formular (`schattendepot`); bis Raphael eine andere festlegt, bei der
    Haselnuss am Ende der Ernte (30. September), beim Palladium nach einem halben Jahr."""
    regel = k.get("schattendepot") or {"bis_monat_tag": "09-30"}
    depot = speicher.lies_json(pfad, None) or {"positionen": []}
    offen = next((p for p in depot["positionen"] if not p.get("schluss_zeit")), None)

    def kurse_jetzt(liste):
        return {e["ticker"]: {"kurs": r[-1]["schluss"], "datum": r[-1]["datum"]}
                for e in liste if (r := reihen.get(e["ticker"]))}

    zeit = zeitpunkt.isoformat(timespec="seconds")
    geaendert = False
    if offen:
        seit = date.fromisoformat(offen["zeit"][:10])
        if regel.get("bis_monat_tag"):
            ende, grund = date.fromisoformat(f"{seit.year}-{regel['bis_monat_tag']}"), "Ende der Ernte"
        else:
            ende, grund = seit + timedelta(days=regel["kalendertage"]), f"nach {regel['kalendertage']} Tagen"
        if heute >= ende:
            offen.update({"schluss_zeit": zeit, "schluss_kurse": kurse_jetzt(k["ersatz"]),
                          "schluss_vergleich": kurse_jetzt([k["vergleich"]]), "schluss_grund": grund})
            offen, geaendert = None, True
    if stufe == "Rot" and not offen:
        kurse_heute = kurse_jetzt(k["ersatz"])
        if kurse_heute:
            offen = {"zeit": zeit, "kurse": kurse_heute, "vergleich": kurse_jetzt([k["vergleich"]]), "grund": "Rot"}
            depot["positionen"].append(offen)
            geaendert = True
    if geaendert:
        speicher.schreibe_json(pfad, depot)
    return {"offen": offen is not None, "seit": offen["zeit"][:10] if offen else None,
            "positionen": len(depot["positionen"])}


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
    teiler.add_argument("--kennung", default="alle", help="haselnuss, palladium oder alle")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    teiler.add_argument("--budget-minuten", type=float, default=20)
    args = teiler.parse_args(argv)
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    kennungen = ([p.stem for p in sorted((konfig.KONFIG / "ersatz").glob("*.yaml"))] if args.kennung == "alle"
                 else [args.kennung])
    fehler = 0
    for kennung in kennungen:
        try:
            stand = lauf(kennung, zeitpunkt.date(), zeitpunkt, args.budget_minuten)
        except Exception as f:  # ein Sensor darf den anderen nicht mitreißen
            print(f"## Ersatz {kennung}: Abbruch, {_fehler(f)}")
            fehler += 1
            continue
        ersatz_text.schreibe(stand, konfig.ABGABE)
        print(ersatz_text.zusammenfassung(stand))
    return 1 if fehler == len(kennungen) else 0


if __name__ == "__main__":
    raise SystemExit(main())
