"""Klimatologie 1991 bis 2020: das „Normal“, gegen das Regen und Wind verglichen werden.

Wird einmal gebaut und danach nur noch gelesen:
- daten/klima/regen.json  mittlerer Tagesregen je Kalendertag und Messpunkt (Ost und West)
- daten/klima/wind.json   mittlerer Ost-West-Wind im Mai und Juni je Punkt vor Sumatra

Fortsetzbar: Nach jedem fertigen Punkt wird gespeichert. Bricht der Lauf ab (Zeitbudget,
Tageslimit von Open-Meteo), macht der nächste Start beim ersten fehlenden Punkt weiter.
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
    gewicht_punkt = sum(openmeteo.gewicht((e - s).days + 1) for s, e in _abschnitte())
    for punkt in punkte:
        if ist_fertig(daten, punkt):
            continue
        _pruefe_budget(budget_ende, gewicht_punkt, pro_minute, f"Regen {punkt['name']}")
        melde(f"Regen {punkt['name']}: hole {VON} bis {BIS} …")
        tageswerte = {}
        for start, ende in _abschnitte():
            try:
                tageswerte.update(openmeteo.hole_tage(om["url"], punkt, start, ende, modell=om.get("modell")))
            finally:
                openmeteo.drossel(openmeteo.gewicht((ende - start).days + 1), pro_minute)
        jahre = Counter(d[:4] for d, w in tageswerte.items() if w is not None)
        volle_jahre = sum(1 for n in jahre.values() if n >= 300)
        if volle_jahre < MINDEST_JAHRE:
            raise Abbruch(f"Regen {punkt['name']}: nur {volle_jahre} vollständige Jahre, erwartet {MINDEST_JAHRE}")
        daten["punkte"][punkt["name"]] = regenzeugen.klimatologie(tageswerte)
        daten["orte"][punkt["name"]] = _ort(punkt)
        daten["jahre_je_punkt"][punkt["name"]] = volle_jahre
        daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
        speicher.schreibe_json(pfad, daten, kompakt=True)
        melde(f"Regen {punkt['name']}: fertig ({volle_jahre} Jahre)")
    daten["fertig"] = True
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
    gewicht_punkt = (BIS - VON + 1) * openmeteo.gewicht(tage, 2)
    for punkt in punkte:
        if ist_fertig(daten, punkt):
            continue
        _pruefe_budget(budget_ende, gewicht_punkt, pro_minute, f"Wind {punkt['name']}")
        melde(f"Wind {punkt['name']}: hole Mai und Juni {VON} bis {BIS} …")
        je_jahr = {}
        for jahr in range(VON, BIS + 1):
            start = date(jahr, monate[0], 1)
            ende = date(jahr, monate[-1], calendar.monthrange(jahr, monate[-1])[1])
            try:
                mittel, _ = openmeteo.hole_mittleren_zonalwind(om["url"], punkt, start, ende,
                                                               modell=om.get("modell"))
                je_jahr[str(jahr)] = round(mittel, 3)
            finally:
                openmeteo.drossel(openmeteo.gewicht(tage, 2), pro_minute)
        daten["punkte"][punkt["name"]] = {"mittel_ms": round(mean(je_jahr.values()), 3),
                                          "jahre": len(je_jahr), "je_jahr": je_jahr}
        daten["orte"][punkt["name"]] = _ort(punkt)
        daten["fertig"] = all(ist_fertig(daten, p) for p in punkte)
        speicher.schreibe_json(pfad, daten)
        melde(f"Wind {punkt['name']}: fertig, Mittel {daten['punkte'][punkt['name']]['mittel_ms']} m/s")
    daten["fertig"] = True
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

    def melde(text: str) -> None:
        print(text, flush=True)
        meldungen.append(text)

    ergebnis = "Klimatologie vollständig."
    try:
        if args.nur in (None, "wind"):
            wind(k, budget_ende, pro_minute, melde)
        if args.nur in (None, "regen"):
            regen(k, budget_ende, pro_minute, melde)
    except Abbruch as grund:
        ergebnis = f"Angehalten: {grund}"
    except AbrufFehler as fehler:
        ergebnis = (f"Angehalten wegen Abruffehler: {fehler}. Der Fortschritt ist gespeichert; "
                    "bei Limit (429) morgen erneut starten.")
    melde(ergebnis)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Klimatologie\n\n" + "\n".join(f"- {m}" for m in meldungen) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
