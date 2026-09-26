"""Ausstiegsregeln: Wann hätte man eine gedachte Position wieder geschlossen? (Auftrag 26.09.2026)

Verglichen an denselben Fällen wie im jeweiligen Rückblick, mit wenigen vorher festgelegten
Varianten aus konfig/ausstieg.yaml:
- Metall: Verschärfungen auf der eigenen Achse; Einstieg zum Schlusskurs am ersten Handelstag ab
  der Ankündigung; Vergleich mit XME über dieselbe Haltedauer.
- Ersatz: Frostjahre; Einstieg am ersten Handelstag nach der ersten Frostnacht; Vergleich mit dem ASX 200.
- Palmöl: Rot-Signale der Lernzeit im Rückblick; Monatsschritte, Einstieg zum Monatsdurchschnitt.
  Preise nur bis zum Ende der Lernzeit, die Prüfzeit bleibt verschlossen.

Je Schritt wird in dieser Reihenfolge geprüft: Verlustgrenze, Gewinnziel, nachgezogene Grenze,
Vorgabe der bisherigen Regel, Haltedauer. Greift nichts, bevor die Reihe endet, bleibt der Fall offen.
Verglichen werden nur Fälle, die unter allen Varianten geschlossen sind, damit alle an denselben
Fällen gemessen werden.

Schreibt daten/ausstieg.json, abgabe/ausstieg-teil-N.md und abgabe/status-ausstieg.md.
Aufruf: python -m anlage.ausstieg [--heute JJJJ-MM-TT]
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import date, datetime, timedelta
from statistics import mean, median

from . import __version__, bilanz, konfig, speicher
from .quellen import kurse

GLEICHAUF = 0.005    # weniger als ein halber Prozentpunkt Abstand gilt als gleichauf
EPS = 1e-9          # Rundungsrest: 120/100 − 1 ist in Gleitkomma knapp unter 0,2
HINWEIS = "Denkhilfe, keine Anlageberatung. Welche Ausstiegsregel gilt, entscheidest du."


# ------------------------------------------------------------------ Regel
def schliessen(werte: list[float], regel: dict, vorgabe: int | None = None, vorgabe_grund: str | None = None) -> dict:
    """werte[0] ist der Einstieg, werte[j] der Stand nach j Schritten.

    Ergebnis: {"schritt", "grund", "rendite"} oder {"offen": True, ...}, wenn die Reihe vorher endet.
    """
    einstieg = werte[0]
    hoch = einstieg
    for j in range(1, len(werte)):
        w = werte[j]
        r = w / einstieg - 1
        hoch = max(hoch, w)
        if regel.get("verlust") is not None and r <= -regel["verlust"] + EPS:
            return _schluss(j, "Verlustgrenze", r)
        if regel.get("ziel") is not None and r >= regel["ziel"] - EPS:
            return _schluss(j, "Gewinnziel", r)
        if (regel.get("nachlauf") is not None and hoch / einstieg - 1 >= regel.get("nachlauf_ab", 0) - EPS
                and w <= hoch * (1 - regel["nachlauf"]) + EPS):
            return _schluss(j, "nachgezogene Grenze", r)
        if vorgabe is not None and j >= vorgabe:
            return _schluss(j, vorgabe_grund or "Vorgabe", r)
        if regel.get("halten") is not None and j >= regel["halten"]:
            return _schluss(j, "Haltedauer", r)
    return {"offen": True, "schritt": len(werte) - 1,
            "rendite": round(werte[-1] / einstieg - 1, 4) if len(werte) > 1 else None}


def _schluss(j: int, grund: str, r: float) -> dict:
    return {"offen": False, "schritt": j, "grund": grund, "rendite": round(r, 4)}


def gipfel(werte: list[float], bis: int) -> float | None:
    """Bester möglicher Ausstieg binnen `bis` Schritten (nur zur Einordnung, nie erreichbar)."""
    teil = werte[1:bis + 1]
    return round(max(teil) / werte[0] - 1, 4) if teil else None


# ------------------------------------------------------------------ Vergleich
def vergleiche(faelle: list[dict], zweig: dict) -> dict:
    """faelle: [{"name", "datum", "werte", "ref" (gleich lang oder None), "vorgabe", "vorgabe_grund"}]."""
    varianten = [{"kennung": "bisher", "bisher": True, **zweig["bisher"]}] + list(zweig["varianten"])
    laengste = max((v.get("halten") or 0) for v in varianten) or 1
    ergebnisse = []
    for f in faelle:
        je = {}
        for v in varianten:
            vorgabe = f.get("vorgabe") if v.get("bisher") else None
            regel = {} if v.get("bisher") else v
            e = schliessen(f["werte"], regel, vorgabe, f.get("vorgabe_grund"))
            if not e["offen"] and f.get("ref"):
                ref = f["ref"]
                e["vergleich"] = round(ref[e["schritt"]] / ref[0] - 1, 4) if ref[0] else None
                e["vorsprung"] = None if e["vergleich"] is None else round(e["rendite"] - e["vergleich"], 4)
            je[v["kennung"]] = e
        ergebnisse.append({k: f[k] for k in ("name", "ticker", "datum", "text", "jahr") if f.get(k) is not None} | {
            "gipfel": gipfel(f["werte"], laengste), "ergebnis": je})
    geschlossen = [e for e in ergebnisse if not any(x["offen"] for x in e["ergebnis"].values())]
    zusammen = []
    for v in varianten:
        werte = [e["ergebnis"][v["kennung"]] for e in geschlossen]
        renditen = [w["rendite"] for w in werte]
        vorsprung = [w["vorsprung"] for w in werte if w.get("vorsprung") is not None]
        zusammen.append({
            "kennung": v["kennung"], "name": v["name"], "kurz": v.get("kurz") or v["name"], "n": len(werte),
            "mittel": _r(mean(renditen)) if renditen else None,
            "median": _r(median(renditen)) if renditen else None,
            "vorsprung": _r(mean(vorsprung)) if vorsprung and len(vorsprung) == len(werte) else None,
            "im_plus": sum(1 for r in renditen if r > 0),
            "schlechtester": min(renditen) if renditen else None,
            "bester": max(renditen) if renditen else None,
            "dauer": _r(mean(w["schritt"] for w in werte), 1) if werte else None,
            "gruende": dict(Counter(w["grund"] for w in werte).most_common()),
        })
    massstab = "vorsprung" if zusammen and all(z["vorsprung"] is not None for z in zusammen) else "mittel"
    reihe = sorted((z for z in zusammen if z[massstab] is not None), key=lambda z: -z[massstab])
    vorn = [z["kennung"] for z in reihe if reihe[0][massstab] - z[massstab] < GLEICHAUF]
    gipfel_werte = [e["gipfel"] for e in geschlossen if e["gipfel"] is not None]
    return {"faelle_gesamt": len(faelle), "verglichen": len(geschlossen),
            "offen": len(faelle) - len(geschlossen), "massstab": massstab,
            "vorn": vorn[0] if len(vorn) == 1 else None, "vorn_gleichauf": vorn if len(vorn) > 1 else [],
            "gipfel_mittel": _r(mean(gipfel_werte)) if gipfel_werte else None,
            "varianten": zusammen, "faelle": ergebnisse}


def _r(x: float, stellen: int = 4) -> float:
    return round(x, stellen)


# ------------------------------------------------------------------ Kursreihen
def _schlusse_ab(reihe: list[dict], i0: int, n: int) -> list[float]:
    return [e["schluss"] for e in reihe[i0:i0 + n + 1]]


def _ref_gleich(reihe: list[dict], ref: list[dict], i0: int, n: int) -> list[float] | None:
    """Vergleichsreihe an denselben Handelstagen (letzter Schluss am oder vor dem Tag)."""
    if not ref:
        return None
    tage = [e["datum"] for e in ref]
    werte = []
    for e in reihe[i0:i0 + n + 1]:
        k = bisect_right(tage, e["datum"]) - 1
        if k < 0:
            return None
        werte.append(ref[k]["schluss"])
    return werte


def _schritt_ab(reihe: list[dict], i0: int, tag_text: str) -> int | None:
    """Erster Handelstag am oder nach `tag_text`, als Schritt ab i0; None, wenn die Reihe vorher endet."""
    k = bisect_left([e["datum"] for e in reihe], tag_text)
    return k - i0 if k < len(reihe) else None


def _einstieg(reihe: list[dict], tag: date) -> int | None:
    """Index des ersten Handelstags ab `tag`, wenn der Wert damals schon gehandelt wurde."""
    i0 = bisect_left([e["datum"] for e in reihe], tag.isoformat())
    if i0 == 0 or i0 >= len(reihe):
        return None
    if (tag - date.fromisoformat(reihe[i0 - 1]["datum"])).days > 10:
        return None
    return i0


# ------------------------------------------------------------------ Zweige
def faelle_metall(k: dict, reihen: dict[str, list[dict]], zweig: dict) -> dict[str, list[dict]]:
    """Je Achse die Fälle aller Werte dieser Achse."""
    laenge = max(v.get("halten") or 0 for v in zweig["varianten"])
    ref = reihen.get(k["vergleich"]["ticker"]) or []
    ereignisse = sorted(k["ereignisse"], key=lambda e: str(e["datum"]))
    je_achse: dict[str, list[dict]] = {}
    for inst in k["instrumente"]:
        reihe = reihen.get(inst["ticker"]) or []
        for e in ereignisse:
            if e["art"] != "verschaerfung" or inst["achse"] not in (e.get("achsen") or []):
                continue
            d = date.fromisoformat(str(e["datum"]))
            i0 = _einstieg(reihe, d)
            if i0 is None:
                continue
            n = max(laenge, 200)
            vorgaben = []
            b = zweig["bisher"]
            if b.get("kalendertage"):
                s = _schritt_ab(reihe, i0, (date.fromisoformat(reihe[i0]["datum"]) + timedelta(days=b["kalendertage"])).isoformat())
                if s is not None:
                    vorgaben.append((s, f"nach {b['kalendertage']} Tagen"))
            if b.get("lockerung"):
                lock = next((x for x in ereignisse if x["art"] == "lockerung" and str(x["datum"]) > str(e["datum"])
                             and inst["achse"] in (x.get("achsen") or [])), None)
                if lock:
                    s = _schritt_ab(reihe, i0, str(lock["datum"]))
                    if s is not None:
                        vorgaben.append((max(s, 1), "Lockerung"))
            vorgabe = min(vorgaben) if vorgaben else (None, None)
            werte = _schlusse_ab(reihe, i0, n)
            je_achse.setdefault(inst["achse"], []).append({
                "name": inst["name"], "ticker": inst["ticker"], "datum": reihe[i0]["datum"], "text": e["text"],
                "werte": werte, "ref": _ref_gleich(reihe, ref, i0, n),
                "vorgabe": vorgabe[0], "vorgabe_grund": vorgabe[1]})
    return je_achse


def faelle_ersatz(k: dict, rueck: dict, reihen: dict[str, list[dict]], zweig: dict) -> list[dict]:
    laenge = max(v.get("halten") or 0 for v in zweig["varianten"])
    ref = reihen.get(k["vergleich"]["ticker"]) or []
    faelle = []
    for e in k["ersatz"]:
        reihe = reihen.get(e["ticker"]) or []
        for x in ((rueck.get("werte") or {}).get(e["ticker"]) or {}).get("faelle") or []:
            d = date.fromisoformat(x["datum"])
            i0 = _einstieg(reihe, d)
            if i0 is None:
                continue
            b = zweig["bisher"]
            if b.get("bis_monat_tag"):
                vorgabe = _schritt_ab(reihe, i0, f"{d.year}-{b['bis_monat_tag']}")
            elif b.get("kalendertage"):
                vorgabe = _schritt_ab(reihe, i0, (date.fromisoformat(reihe[i0]["datum"]) + timedelta(days=b["kalendertage"])).isoformat())
            else:
                vorgabe = None
            n = max(laenge, (vorgabe or 0))
            faelle.append({"name": e["name"], "ticker": e["ticker"], "datum": reihe[i0]["datum"], "jahr": x.get("jahr"),
                           "werte": _schlusse_ab(reihe, i0, n), "ref": _ref_gleich(reihe, ref, i0, n),
                           "vorgabe": vorgabe if vorgabe and vorgabe > 0 else None,
                           "vorgabe_grund": "Ende der Ernte" if b.get("bis_monat_tag") else f"nach {b.get('kalendertage')} Tagen"})
    return faelle


def faelle_palmoel(rueck: dict, preisreihe: list[dict], zweig: dict) -> list[dict]:
    """Rot-Signale der Lernzeit; Preise nur bis zum Ende der Lernzeit."""
    bis = bilanz.monats_index(rueck["einstellungen"]["lernzeit_bis"])
    preise = bilanz.preis_nach_monat(preisreihe, bis)
    laenge = max(v.get("halten") or 0 for v in zweig["varianten"])
    faelle = []
    for s in (rueck.get("lernzeit") or {}).get("bilanz", {}).get("signale") or []:
        i = bilanz.monats_index(s["monat"])
        if i not in preise:
            continue
        schluss = bilanz.monats_index(s["schluss"]) - i if s.get("schluss") else None
        n = max(laenge, schluss or 0)
        werte = []
        for j in range(i, i + n + 1):
            if j not in preise:
                break
            werte.append(preise[j])
        faelle.append({"name": "Palmöl", "datum": s["monat"], "werte": werte, "ref": None,
                       "vorgabe": schluss if schluss and schluss > 0 else None, "vorgabe_grund": "Grün"})
    return faelle


# ------------------------------------------------------------------ Lauf
def _archive(ordner, ticker: list[str]) -> dict[str, list[dict]]:
    return {t: kurse.lies_archiv(kurse.archiv_pfad(ordner / "kurse", t)) for t in ticker}


def lauf(zeitpunkt: datetime) -> dict:
    a = konfig.lade_yaml(konfig.KONFIG / "ausstieg.yaml")
    zweige = a["zweige"]
    ergebnis = {"stand": zeitpunkt.isoformat(timespec="seconds"), "datum": zeitpunkt.date().isoformat(),
                "version": __version__, "hinweis": HINWEIS, "gilt": a.get("gilt") or {}, "zweige": {}}

    # Metall
    for pfad in sorted((konfig.KONFIG / "metalle").glob("*.yaml")):
        k = konfig.lade_yaml(pfad)
        o = konfig.DATEN / "metall" / k["kennung"]
        reihen = _archive(o, [i["ticker"] for i in k["instrumente"]] + [k["vergleich"]["ticker"]])
        achsen = {}
        for achse, faelle in faelle_metall(k, reihen, zweige["metall"]).items():
            achsen[achse] = {"name": k["achsen"][achse]["name"],
                             "werte": sorted({f["name"] for f in faelle}), **vergleiche(faelle, zweige["metall"])}
        ergebnis["zweige"][f"metall_{k['kennung']}"] = {
            "art": "metall", "name": f"Metall {k['name']}", "einheit": zweige["metall"]["einheit"],
            "einstieg": zweige["metall"]["einstieg"], "spaetestens": zweige["metall"].get("spaetestens"),
            "vergleich": k["vergleich"]["name"],
            "achsen": achsen, "status": "ok" if achsen else "keine Kurse"}

    # Ersatz
    for pfad in sorted((konfig.KONFIG / "ersatz").glob("*.yaml")):
        k = konfig.lade_yaml(pfad)
        z = zweige.get(f"ersatz_{k['kennung']}")
        if not z:
            continue
        o = konfig.DATEN / "ersatz" / k["kennung"]
        rueck = speicher.lies_json(o / "rueckblick.json", None)
        eintrag = {"art": "ersatz", "name": f"Ersatz {k['name']}", "einheit": z["einheit"],
                   "einstieg": z["einstieg"], "spaetestens": z.get("spaetestens"),
                   "vergleich": k["vergleich"]["name"],
                   "ersatz": [e["name"] for e in k["ersatz"]]}
        if not rueck:
            eintrag["status"] = "Rückblick fehlt"
        else:
            reihen = _archive(o, [e["ticker"] for e in k["ersatz"]] + [k["vergleich"]["ticker"]])
            eintrag.update({"status": "ok", **vergleiche(faelle_ersatz(k, rueck, reihen, z), z)})
        ergebnis["zweige"][f"ersatz_{k['kennung']}"] = eintrag

    # Palmöl
    rueck = speicher.lies_json(konfig.RUECKBLICK / "palmoel.json", None)
    eintrag = {"art": "palmoel", "name": "Palmöl", "einheit": zweige["palmoel"]["einheit"],
               "einstieg": zweige["palmoel"]["einstieg"], "spaetestens": zweige["palmoel"].get("spaetestens"),
               "vergleich": None}
    preise = ((speicher.lies_json(konfig.GESCHICHTE / "preise.json") or {}).get("reihen") or {}).get("palmoel")
    if not rueck or not preise:
        eintrag["status"] = "Rückblick fehlt"
    else:
        reihe = sorted((e for e in preise if e.get("wert")), key=lambda e: e["datum"])
        eintrag.update({"status": "ok", "lernzeit_bis": rueck["einstellungen"]["lernzeit_bis"],
                        **vergleiche(faelle_palmoel(rueck, reihe, zweige["palmoel"]), zweige["palmoel"])})
    ergebnis["zweige"]["palmoel"] = eintrag

    ergebnis["zustand"] = "in Ordnung" if any(z["status"] == "ok" for z in ergebnis["zweige"].values()) else "Warnung"
    speicher.schreibe_json(konfig.DATEN / "ausstieg.json", ergebnis)
    return ergebnis


def main(argv: list[str] | None = None) -> int:
    from .ausgabe import ausstieg_text

    teiler = argparse.ArgumentParser(description="Ausstiegsregeln an den Fällen der Rückblicke vergleichen")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    args = teiler.parse_args(argv)
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    ergebnis = lauf(zeitpunkt)
    ausstieg_text.schreibe(ergebnis, konfig.ABGABE)
    print(ausstieg_text.zusammenfassung(ergebnis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
