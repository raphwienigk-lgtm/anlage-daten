"""Klimatologie 1991 bis 2020: das „Normal“, gegen das Regen und Wind verglichen werden.

Wird einmal gebaut und danach nur noch gelesen:
- daten/klima/regen.json  mittlerer Tagesregen je Kalendertag und Messpunkt (Ost und West)
- daten/klima/wind.json   mittlerer Ost-West-Wind im Mai und Juni je Punkt vor Sumatra

Fortsetzbar: Jeder geholte Fünfjahresblock (Regen) und jedes Jahr (Wind) wird sofort in
daten/klima/teilweise.json gesichert; ein fertiger Punkt wandert ins Normal. Bricht der
Lauf ab (Zeitbudget, Tageslimit von Open-Meteo), macht der nächste Start dort weiter.
Scheitert ein einzelner Punkt, geht es mit dem nächsten weiter. Was passiert ist, steht
in daten/klima/lauf-klimatologie.json (lesbar ohne Anmeldung bei GitHub).
Dauer insgesamt etwa zwei Stunden, weil Open-Meteo lange Zeiträume mehrfach anrechnet.

Aufruf: python -m anlage.klimatologie [--nur regen|wind] [--budget-minuten 150]
"""
from __future__ import annotations

import argparse
import calendar
import os
import time
from collections import Counter
from datetime import date
from statistics import mean

from . import konfig, speicher
from .module import regenzeugen
from .netz import AbrufFehler
from .quellen import openmeteo

VON, BIS = 1991, 2020
JAHRE_PRO_ABRUF = 5
MINDEST_JAHRE = 25


class Abbruch(Exception):
    """Sauber anhalten, Fortschritt ist gespeichert."""


def _ort(punkt: dict) -> dict:
    return {"lat": punkt["lat"], "lon": punkt["lon"]}


class Zwischenstand:
    """Teilergebnisse je Punkt, damit ein Abbruch nichts verliert."""

    def __init__(self):
        self.pfad = konfig.KLIMA / "teilweise.json"
        self.daten = speicher.lies_json(self.pfad, {}) or {}

    def hole(self, art: str, punkt: dict) -> dict:
        eintrag = self.daten.get(art, {}).get(punkt["name"])
        if not eintrag or eintrag.get("ort") != _ort(punkt):
            return {}
        return dict(eintrag["werte"])

    def merke(self, art: str, punkt: dict, werte: dict) -> None:
        self.daten.setdefault(art, {})[punkt["name"]] = {"ort": _ort(punkt), "werte": werte}
        speicher.schreibe_json(self.pfad, self.daten, kompakt=True)

    def fertig(self, art: str, punkt: dict) -> None:
        self.daten.get(art, {}).pop(punkt["name"], None)
        self.daten = {a: e for a, e in self.daten.items() if e}
        if self.daten:
            speicher.schreibe_json(self.pfad, self.daten, kompakt=True)
        elif self.pfad.exists():
            self.pfad.unlink()


def _fehler_behandeln(fehler: AbrufFehler, was: str, melde) -> None:
    """429 heißt Limit: anhalten, morgen weiter. Alles andere: melden, nächster Punkt."""
    if "429" in str(fehler):
        raise Abbruch(f"Open-Meteo-Limit erreicht bei {was}. Später noch einmal starten; nichts geht verloren.")
    melde(f"Fehler bei {was}: {fehler}")


def ist_fertig(daten: dict | None, punkt: dict) -> bool:
    """Liegt für diesen Punkt (an diesem Ort) schon ein Normalwert vor?"""
    daten = daten or {}
    return punkt["name"] in daten.get("punkte", {}) and daten.get("orte", {}).get(punkt["name"]) == _ort(punkt)


def _abschnitte() -> list[tuple[date, date]]:
    return [(date(j, 1, 1), date(min(j + JAHRE_PRO_ABRUF - 1, BIS), 12, 31))
            for j in range(VON, BIS + 1, JAHRE_PRO_ABRUF)]


def _pruefe_budget(budget_ende: float, gewicht: float, pro_minute: float, was: str) -> None:
    dauer = 60.0 * gewicht / pro_minute if pro_minute else 0
    if time.monotonic() + dauer > budget_ende:
        raise Abbruch(f"Zeitbudget reicht nicht mehr für {was}. Einfach noch einmal starten.")


def regen(k: dict, budget_ende: float, pro_minute: float, melde=print) -> dict:
    om = k["quellen"]["openmeteo"]
    pfad = konfig.KLIMA / "regen.json"
    daten = speicher.lies_json(pfad, {}) or {}
    for feld in ("punkte", "orte", "jahre_je_punkt"):
        daten.setdefault(feld, {})
    daten.update({"zeitraum": f"{VON}–{BIS}", "modell": om.get("modell"), "einheit": "mm je Tag"})
    punkte = k["regionen"]["ost"]["punkte"] + k["regionen"]["west"]["punkte"]
    daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
    zwischen = Zwischenstand()
    for punkt in punkte:
        if ist_fertig(daten, punkt):
            continue
        tageswerte = zwischen.hole("regen", punkt)
        schon = {d[:4] for d in tageswerte}
        offen = [(s, e) for s, e in _abschnitte() if str(s.year) not in schon]
        melde(f"Regen {punkt['name']}: hole {VON} bis {BIS} …" if not schon
              else f"Regen {punkt['name']}: mache weiter, {len(offen)} von {len(_abschnitte())} Blöcken fehlen …")
        try:
            for start, ende in offen:
                gewicht = openmeteo.gewicht((ende - start).days + 1)
                _pruefe_budget(budget_ende, gewicht, pro_minute, f"Regen {punkt['name']} ab {start.year}")
                try:
                    tageswerte.update(openmeteo.hole_tage(om["url"], punkt, start, ende, modell=om.get("modell")))
                finally:
                    openmeteo.drossel(gewicht, pro_minute)
                zwischen.merke("regen", punkt, tageswerte)
        except AbrufFehler as fehler:
            _fehler_behandeln(fehler, f"Regen {punkt['name']}", melde)
            continue
        jahre = Counter(d[:4] for d, w in tageswerte.items() if w is not None)
        volle_jahre = sum(1 for n in jahre.values() if n >= 300)
        if volle_jahre < MINDEST_JAHRE:
            melde(f"Regen {punkt['name']}: nur {volle_jahre} vollständige Jahre, erwartet {MINDEST_JAHRE}; "
                  "der Punkt wird beim nächsten Start neu geholt")
            zwischen.fertig("regen", punkt)
            continue
        daten["punkte"][punkt["name"]] = regenzeugen.klimatologie(tageswerte)
        daten["orte"][punkt["name"]] = _ort(punkt)
        daten["jahre_je_punkt"][punkt["name"]] = volle_jahre
        daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
        speicher.schreibe_json(pfad, daten, kompakt=True)
        zwischen.fertig("regen", punkt)
        melde(f"Regen {punkt['name']}: fertig ({volle_jahre} Jahre)")
    daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
    speicher.schreibe_json(pfad, daten, kompakt=True)
    return daten


def wind(k: dict, budget_ende: float, pro_minute: float, melde=print) -> dict:
    om = k["quellen"]["openmeteo"]
    monate = k["schwellen"]["dipol"]["wind_monate"]
    pfad = konfig.KLIMA / "wind.json"
    daten = speicher.lies_json(pfad, {}) or {}
    for feld in ("punkte", "orte"):
        daten.setdefault(feld, {})
    daten.update({"zeitraum": f"{VON}–{BIS}", "modell": om.get("modell"), "monate": monate,
                  "einheit": "m/s, negativ = Wind aus Osten"})
    punkte = k["regionen"]["wind_sumatra"]["punkte"]
    daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
    tage = (date(2001, monate[-1], calendar.monthrange(2001, monate[-1])[1]) - date(2001, monate[0], 1)).days + 1
    gewicht_jahr = openmeteo.gewicht(tage, 2)
    zwischen = Zwischenstand()
    for punkt in punkte:
        if ist_fertig(daten, punkt):
            continue
        je_jahr = zwischen.hole("wind", punkt)
        melde(f"Wind {punkt['name']}: hole Mai und Juni {VON} bis {BIS} …" if not je_jahr
              else f"Wind {punkt['name']}: mache weiter, {BIS - VON + 1 - len(je_jahr)} Jahre fehlen …")
        try:
            for jahr in range(VON, BIS + 1):
                if str(jahr) in je_jahr:
                    continue
                _pruefe_budget(budget_ende, gewicht_jahr, pro_minute, f"Wind {punkt['name']} {jahr}")
                start = date(jahr, monate[0], 1)
                ende = date(jahr, monate[-1], calendar.monthrange(jahr, monate[-1])[1])
                try:
                    mittel, _ = openmeteo.hole_mittleren_zonalwind(om["url"], punkt, start, ende,
                                                                   modell=om.get("modell"))
                finally:
                    openmeteo.drossel(gewicht_jahr, pro_minute)
                je_jahr[str(jahr)] = round(mittel, 3)
                zwischen.merke("wind", punkt, je_jahr)
        except AbrufFehler as fehler:
            _fehler_behandeln(fehler, f"Wind {punkt['name']}", melde)
            continue
        daten["punkte"][punkt["name"]] = {"mittel_ms": round(mean(je_jahr.values()), 3),
                                          "jahre": len(je_jahr), "je_jahr": je_jahr}
        daten["orte"][punkt["name"]] = _ort(punkt)
        daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
        speicher.schreibe_json(pfad, daten)
        zwischen.fertig("wind", punkt)
        melde(f"Wind {punkt['name']}: fertig, Mittel {daten['punkte'][punkt['name']]['mittel_ms']} m/s")
    daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
    speicher.schreibe_json(pfad, daten)
    return daten


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Klimatologie 1991 bis 2020 bauen (einmalig, fortsetzbar)")
    teiler.add_argument("--nur", choices=["regen", "wind"])
    teiler.add_argument("--budget-minuten", type=float, default=150)
    teiler.add_argument("--pro-minute", type=float, default=None,
                        help="gewichtete Abrufe je Minute (Standard aus quellen.yaml)")
    args = teiler.parse_args(argv)
    k = konfig.konfiguration()
    pro_minute = args.pro_minute if args.pro_minute is not None else k["quellen"]["openmeteo"]["gewicht_pro_minute"]
    budget_ende = time.monotonic() + args.budget_minuten * 60
    meldungen = []
    regionen = k["regionen"]
    noetig = {"wind": (konfig.KLIMA / "wind.json", regionen["wind_sumatra"]["punkte"]),
              "regen": (konfig.KLIMA / "regen.json", regionen["ost"]["punkte"] + regionen["west"]["punkte"])}
    offen = [art for art, (pfad, punkte) in noetig.items() if args.nur in (None, art)
             and not all(ist_fertig(speicher.lies_json(pfad), p) for p in punkte)]
    if not offen:
        print("Klimatologie ist vollständig, nichts zu tun.")
        return 0

    def melde(text: str) -> None:
        print(text, flush=True)
        meldungen.append(text)

    fertig = {}
    ergebnis = None
    try:
        if args.nur in (None, "wind"):
            fertig["wind"] = wind(k, budget_ende, pro_minute, melde)["fertig"]
        if args.nur in (None, "regen"):
            fertig["regen"] = regen(k, budget_ende, pro_minute, melde)["fertig"]
    except Abbruch as grund:
        ergebnis = f"Angehalten: {grund}"
    except Exception as fehler:                     # auch Unerwartetes landet in der Statusdatei
        ergebnis = f"Angehalten wegen {type(fehler).__name__}: {fehler}. Der Fortschritt ist gespeichert."
    if ergebnis is None:
        ergebnis = ("Klimatologie vollständig." if all(fertig.values())
                    else "Einzelne Punkte fehlen noch (siehe Meldungen). Einfach noch einmal starten.")
    melde(ergebnis)
    speicher.schreibe_json(konfig.KLIMA / "lauf-klimatologie.json",
                           {"stand": konfig.jetzt().isoformat(timespec="seconds"), "ergebnis": ergebnis,
                            "fertig": fertig, "meldungen": meldungen})
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Klimatologie\n\n" + "\n".join(f"- {m}" for m in meldungen) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
