"""Gesamt-Schattendepot, Teil auf GitHub (Auftrag 27.09.2026).

Das Rechnen selbst steckt im eigenständigen Werkzeug werkzeuge/schattendepot.py, damit der Depot-Agent in der
Cloud es ohne Installation ausführen kann; dort kommt das Schattendepot des Metall-Wächters dazu, das GitHub nicht
kennt. Dieser Lauf bereitet alles vor:

- holt die Devisenkurse (Euro zu Dollar, Singapur-Dollar, Australischem Dollar) ins Archiv daten/depot/kurse/,
- schreibt daten/depot/index.json: jeder Wert aller Zweige mit Name, Währung, Kursarchiv und Vergleichsmaßstab,
  die Quellen der gedachten Positionen, die geltende Ausstiegsregel je Zweig und die Liste aller Dateien,
- rechnet zur Probe das Schattendepot ohne die Metall-Positionen und schreibt abgabe/status-depot.md.

Aufruf: python -m anlage.depot [--heute JJJJ-MM-TT]
"""
from __future__ import annotations

import argparse
import importlib.util
from datetime import date, datetime

from . import __version__, konfig, speicher
from .quellen import kurse

WERKZEUG = konfig.BASIS / "werkzeuge" / "schattendepot.py"


def werkzeug():
    spec = importlib.util.spec_from_file_location("schattendepot", WERKZEUG)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _rel(pfad) -> str:
    """Pfad im Repository, unabhängig davon, wohin die Tests daten/ umleiten."""
    return "daten/" + pfad.relative_to(konfig.DATEN).as_posix()


def devisen(d: dict, holen=None) -> tuple[dict[str, str], list[str]]:
    holen = holen or kurse.hole_yahoo
    ab = str(d.get("kurse_ab") or "2010-01-04")
    pfade, fehler = {}, []
    for waehrung, ticker in (d.get("devisen") or {}).items():
        pfad = kurse.archiv_pfad(konfig.DATEN / "depot" / "kurse", ticker)
        try:
            kurse.ergaenze_archiv(pfad, [e for e in holen(ticker, "max") if e["datum"] >= ab])
        except Exception as f:  # eine Währung darf die anderen nicht mitreißen
            fehler.append(f"{ticker}: {type(f).__name__}: {f}"[:200])
        if pfad.exists():
            pfade[waehrung] = _rel(pfad)
    return pfade, fehler


def index(d: dict, devisen_pfade: dict[str, str], zeitpunkt: datetime) -> dict:
    ausstieg = konfig.lade_yaml(konfig.KONFIG / "ausstieg.yaml")
    gilt, regeln = ausstieg.get("gilt") or {}, ausstieg.get("zweige") or {}
    werte, vergleiche, zweige = {}, {}, {}

    def zweig(kennung: str, name: str, quelle: dict):
        r = regeln.get(kennung) or {}
        g = gilt.get(kennung, "bisher")
        regel = r.get("bisher") if g == "bisher" else next((v for v in r.get("varianten", []) if v["kennung"] == g), None)
        zweige[kennung] = {"name": name, "quelle": quelle, "gilt": g, "regel": regel,
                           "regel_name": (regel or {}).get("name")}

    # Agrar-Rohstoffe: Rot kauft jeden Wert unter instrumente gedacht
    for pfad in sorted((konfig.KONFIG / "rohstoffe").glob("*.yaml")):
        r = konfig.lade_yaml(pfad)
        if r.get("rolle") == "verworfen":
            continue
        zweig(r["kennung"], r["name"], {"art": "logbuch", "pfad": "daten/signale.jsonl", "rohstoff": r["kennung"]})
        for i in r.get("instrumente") or []:
            werte[i["ticker"]] = {"name": i["name"], "zweig": r["kennung"],
                                  "waehrung": i.get("waehrung") or (d.get("boerse_waehrung") or {}).get(i.get("boerse")),
                                  "archiv": _rel(kurse.archiv_pfad(konfig.PREISE, i["ticker"])), "vergleich": None}

    # Metall: das Schattendepot führt der Metall-Wächter in der Cloud, es kommt als Zusatz dazu
    for pfad in sorted((konfig.KONFIG / "metalle").glob("*.yaml")):
        m = konfig.lade_yaml(pfad)
        kennung = "metall" if m["kennung"] == "china" else f"metall_{m['kennung']}"
        zweig(kennung, f"Metall {m['name']}", {"art": "zusatz", "herkunft": "metall-logbuch.md (Metall-Wächter)"})
        o = konfig.DATEN / "metall" / m["kennung"] / "kurse"
        ref = m["vergleich"]
        vergleiche[ref["ticker"]] = {"name": ref["name"], "archiv": _rel(kurse.archiv_pfad(o, ref["ticker"]))}
        for i in m.get("instrumente") or []:
            werte[i["ticker"]] = {"name": i["name"], "zweig": kennung, "waehrung": i.get("waehrung"),
                                  "archiv": _rel(kurse.archiv_pfad(o, i["ticker"])), "vergleich": ref["ticker"],
                                  "achse": i.get("achse"), "rolle": i.get("rolle")}

    # Ersatz-Sensoren
    for pfad in sorted((konfig.KONFIG / "ersatz").glob("*.yaml")):
        k = konfig.lade_yaml(pfad)
        kennung = f"ersatz_{k['kennung']}"
        o = konfig.DATEN / "ersatz" / k["kennung"]
        zweig(kennung, f"Ersatz {k['name']}", {"art": "ersatz", "pfad": _rel(o / "schattendepot.json")})
        ref = k["vergleich"]
        vergleiche[ref["ticker"]] = {"name": ref["name"], "archiv": _rel(kurse.archiv_pfad(o / "kurse", ref["ticker"]))}
        for e in k.get("ersatz") or []:
            werte[e["ticker"]] = {"name": e["name"], "zweig": kennung, "waehrung": e.get("waehrung"),
                                  "archiv": _rel(kurse.archiv_pfad(o / "kurse", e["ticker"])), "vergleich": ref["ticker"],
                                  "rolle": e.get("rolle")}

    dateien = ["daten/depot/index.json", "werkzeuge/schattendepot.py"]
    dateien += sorted({z["quelle"]["pfad"] for z in zweige.values() if z["quelle"].get("pfad")})
    dateien += sorted({w["archiv"] for w in werte.values()} | {v["archiv"] for v in vergleiche.values()}
                      | set(devisen_pfade.values()))
    return {
        "stand": zeitpunkt.isoformat(timespec="seconds"),
        "version": __version__,
        "hinweis": "Reine Rechnung mit einem erfundenen Betrag, kein echtes Geld. Denkhilfe, keine Anlageberatung.",
        "betrag": d.get("betrag", 1000),
        "basis": d.get("basis", "EUR"),
        "devisen": devisen_pfade,
        "werte": werte,
        "vergleiche": vergleiche,
        "zweige": zweige,
        "dateien": dateien,
    }


def lauf(zeitpunkt: datetime, holen=None) -> dict:
    d = konfig.lade_yaml(konfig.KONFIG / "depot.yaml")
    devisen_pfade, fehler = devisen(d, holen)
    idx = index(d, devisen_pfade, zeitpunkt)
    speicher.schreibe_json(konfig.DATEN / "depot" / "index.json", idx)

    # Probe: Schattendepot ohne die Metall-Positionen aus der Cloud
    fehlen = [w for w in idx["werte"].values() if not (konfig.DATEN / w["archiv"][len("daten/"):]).exists()]
    probe = werkzeug().rechnen(konfig.DATEN.parent, zeitpunkt.date())
    zustand = "Fehler" if len(fehler) == len(d.get("devisen") or {}) and fehler else (
        "Warnung" if fehler or fehlen or probe["fehler"] else "in Ordnung")
    ergebnis = {"stand": idx["stand"], "zustand": zustand, "devisen_fehler": fehler,
                "ohne_archiv": sorted(w["name"] for w in fehlen), "probe": probe["gesamt"],
                "probe_fehler": probe["fehler"], "werte": len(idx["werte"])}
    status = ("Agent: Schattendepot (Vorbereitung auf GitHub; gerechnet wird beim Depot-Agenten)\n"
              f"Stand: {zeitpunkt.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {zustand}\n"
              "Ergebnis: daten/depot/index.json, daten/depot/kurse/\n"
              f"Werte: {len(idx['werte'])}, davon ohne Kursarchiv: {len(fehlen)}\n"
              f"Probe ohne Metall: {probe['gesamt']['offen']['anzahl']} offene, "
              f"{probe['gesamt']['geschlossen']['anzahl']} geschlossene gedachte Positionen\n")
    if fehler:
        status += "Devisen: " + "; ".join(fehler)[:300] + "\n"
    speicher.schreibe_text(konfig.ABGABE / "status-depot.md", status)
    return ergebnis


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Schattendepot vorbereiten: Devisen, Index, Probe")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    args = teiler.parse_args(argv)
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    ergebnis = lauf(zeitpunkt)
    print(f"Schattendepot vorbereitet: {ergebnis['werte']} Werte, Zustand {ergebnis['zustand']}")
    for f in ergebnis["devisen_fehler"] + ergebnis["probe_fehler"]:
        print(f"  {f}")
    return 1 if ergebnis["zustand"] == "Fehler" else 0


if __name__ == "__main__":
    raise SystemExit(main())
