"""Prüflauf: Ist jede Quelle erreichbar und lesbar? Holt nur kleine Stichproben.

Schreibt daten/quellen-status.json und druckt eine Liste. Gedacht für die Einrichtung
und für den Fall, dass im Stand eine Quelle als Fehler auftaucht.

Aufruf: python -m anlage.pruefen [--streng]   (--streng: Rückgabewert 1, wenn etwas fehlt)
"""
from __future__ import annotations

import argparse
import os
from datetime import timedelta

from . import konfig, netz, speicher
from .quellen import klimaindizes, kurse, openmeteo


def _probe(name: str, aufgabe) -> dict:
    try:
        stand = aufgabe()
        return {"name": name, "status": "ok", "stand": stand}
    except Exception as fehler:
        return {"name": name, "status": "Fehler", "meldung": f"{type(fehler).__name__}: {fehler}"}


def pruefe(k: dict) -> list[dict]:
    q = k["quellen"]
    heute = konfig.jetzt().date()
    ergebnisse = []

    def oni():
        r = klimaindizes.hole_oni(q["oni"]["url"])
        return f"{r[-1]['jahreszeit']} {r[-1]['jahr']}: {r[-1]['wert']:+.2f}"
    ergebnisse.append(_probe(q["oni"]["name"], oni))

    for quelle in q["dmi"]["urls"]:
        def dmi(url=quelle["url"]):
            r = klimaindizes.lies_monatsreihe(netz.hole_text(url))
            return f"{r[-1]['jahr']}-{r[-1]['monat']:02d}: {r[-1]['wert']:+.2f}"
        ergebnisse.append(_probe(f"Dipol-Index, {quelle['name']}", dmi))

    om = q["openmeteo"]
    punkt = k["regionen"]["ost"]["punkte"][0]

    def regen():
        werte = openmeteo.hole_tage(om["url"], punkt, heute - timedelta(days=12), heute - timedelta(days=2),
                                    modell=om.get("modell"))
        gemessen = [d for d, w in werte.items() if w is not None]
        return f"{punkt['name']}: {len(gemessen)} von {len(werte)} Tagen, letzter Messtag {max(gemessen) if gemessen else '–'}"
    ergebnisse.append(_probe("Open-Meteo Regen", regen))

    wpunkt = k["regionen"]["wind_sumatra"]["punkte"][0]

    def wind():
        u, stunden = openmeteo.hole_mittleren_zonalwind(om["url"], wpunkt, heute - timedelta(days=12),
                                                        heute - timedelta(days=9), modell=om.get("modell"))
        return f"{wpunkt['name']}: Ost-West-Wind {u:+.1f} m/s aus {stunden} Stunden"
    ergebnisse.append(_probe("Open-Meteo Wind", wind))

    serien = sorted({r["preis"]["serie"] for r in k["rohstoffe"].values() if r["preis"]["quelle"] == "fred"})
    for serie in serien:
        def fred(serie=serie):
            r = kurse.hole_fred(q["fred"]["url"], serie)
            return f"{r[-1]['datum']}: {r[-1]['wert']}"
        ergebnisse.append(_probe(f"FRED {serie}", fred))

    tickers = sorted(set(q["yahoo"]["gegenkraefte"].values())
                     | {i["ticker"] for r in k["rohstoffe"].values() for i in r.get("instrumente", [])})
    for ticker in tickers:
        def yahoo(ticker=ticker):
            r = kurse.hole_yahoo(ticker, "5d")
            return f"{r[-1]['datum']}: {r[-1]['schluss']}"
        ergebnisse.append(_probe(f"Yahoo {ticker}", yahoo))
    return ergebnisse


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Prüflauf aller Datenquellen")
    teiler.add_argument("--streng", action="store_true", help="Rückgabewert 1, wenn eine Quelle fehlt")
    args = teiler.parse_args(argv)
    k = konfig.konfiguration()
    for kennung, eintrag in k["rohstoffe"].items():
        for fehler in konfig.pruefe_rohstoff(eintrag, k["regionen"]):
            print(f"Formular {kennung}: {fehler}")
    ergebnisse = pruefe(k)
    speicher.schreibe_json(konfig.DATEN / "quellen-status.json",
                           {"stand": konfig.jetzt().isoformat(timespec="seconds"), "quellen": ergebnisse})
    zeilen = []
    for e in ergebnisse:
        zeichen = "OK    " if e["status"] == "ok" else "FEHLER"
        zeilen.append(f"{zeichen}  {e['name']}: {e.get('stand') or e.get('meldung')}")
    text = "\n".join(zeilen)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Prüflauf\n\n```\n" + text + "\n```\n")
    fehlend = sum(1 for e in ergebnisse if e["status"] != "ok")
    print(f"\n{len(ergebnisse) - fehlend} von {len(ergebnisse)} Quellen in Ordnung.")
    return 1 if (args.streng and fehlend) else 0


if __name__ == "__main__":
    raise SystemExit(main())
