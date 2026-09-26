"""Inlandspreise als Frühzeichen für den Politik-Kanal.

Täglich vor dem Tageslauf: holt die Inlandspreise, die in den Rohstoff-Formularen unter
`inlandspreise` stehen, ergänzt die Archive unter daten/inland/ und rechnet je Reihe.
Die Geschichte von Bank Indonesia wird in kleinen Stücken rückwärts nachgeholt, je Lauf
höchstens `--budget-minuten` lang. Je Reihe:

- Frühzeichen (Rolle „fruehzeichen“): Mittel der letzten vier Wochen gegen dasselbe
  Mittel zwölf Wochen früher. Ab plus 10 Prozent gilt es als Frühzeichen, ab plus
  20 Prozent als starkes. Monatsreihen vergleichen den letzten Wert mit dem von vor
  drei Monaten.
- Tagespreise (Rolle „tagespreis“) und Ersatzreihen werden nur berichtet.

Das Frühzeichen ändert die Ampel nicht; es ist nicht am Rückblick geprüft (die Reihen
beginnen erst 2017). Es steht im Stand und im Vorlesetext.

Schreibt daten/inland/<kennung>.json, daten/inlandspreise.json, abgabe/status-inlandspreise.md.
Aufruf: python -m anlage.inlandspreise [--heute JJJJ-MM-TT] [--budget-minuten 10]
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta
from statistics import mean, median

from . import __version__, konfig, speicher
from .quellen import inland

HINWEIS = "Denkhilfe, keine Anlageberatung. Frühzeichen, nicht am Rückblick geprüft."


def archiv_pfad(kennung: str):
    return konfig.INLAND / f"{kennung}.json"


def ergaenze(pfad, neu: list[dict]) -> list[dict]:
    """Neue Werte überschreiben alte am selben Tag; sortiert nach Datum."""
    alt = {e["datum"]: e for e in (speicher.lies_json(pfad, []) or [])}
    for e in neu:
        alt[e["datum"]] = {"datum": e["datum"], "wert": e["wert"]}
    reihe = [alt[d] for d in sorted(alt)]
    speicher.schreibe_json(pfad, reihe, kompakt=True)
    return reihe


def _mittel(reihe: list[dict], bis: date, tage: int) -> tuple[float | None, int]:
    von = bis - timedelta(days=tage - 1)
    werte = [e["wert"] for e in reihe if von.isoformat() <= e["datum"] <= bis.isoformat()]
    return (mean(werte) if werte else None), len(werte)


def ist_monatsreihe(reihe: list[dict]) -> bool:
    if len(reihe) < 3:
        return False
    tage = [date.fromisoformat(e["datum"]) for e in reihe[-13:]]
    abstaende = [(b - a).days for a, b in zip(tage, tage[1:])]
    return median(abstaende) > 20


def fruehzeichen(reihe: list[dict], heute: date, s: dict) -> dict:
    """Veränderung und Urteil einer Reihe. Ohne genug Werte: kein Urteil."""
    if not reihe:
        return {"urteil": "keine Daten"}
    letzter = reihe[-1]
    alter = (heute - date.fromisoformat(letzter["datum"])).days
    ergebnis = {"letzter": letzter, "alter_tage": alter}
    if ist_monatsreihe(reihe):
        ziel = date.fromisoformat(letzter["datum"]) - timedelta(days=80)
        frueher = [e for e in reihe if e["datum"] <= ziel.isoformat()]
        if not frueher:
            return {**ergebnis, "urteil": "zu kurz", "art": "monatlich"}
        veraenderung = letzter["wert"] / frueher[-1]["wert"] - 1
        ergebnis.update({"art": "monatlich", "vergleich": frueher[-1]})
    else:
        ende = date.fromisoformat(letzter["datum"])
        jetzt, n_jetzt = _mittel(reihe, ende, s["mittel_tage"])
        damals, n_damals = _mittel(reihe, ende - timedelta(days=s["abstand_tage"]), s["mittel_tage"])
        if n_jetzt < s["mindest_werte"] or n_damals < s["mindest_werte"] or not damals:
            return {**ergebnis, "urteil": "zu kurz", "art": "täglich"}
        veraenderung = jetzt / damals - 1
        ergebnis.update({"art": "täglich", "mittel_jetzt": round(jetzt, 2), "mittel_damals": round(damals, 2)})
    ergebnis["veraenderung"] = round(veraenderung, 4)
    grenze = s.get("veraltet_nach_tage_monat", 100) if ergebnis["art"] == "monatlich" else s["veraltet_nach_tage"]
    if alter > grenze:
        ergebnis["urteil"] = "veraltet"
    elif veraenderung >= s["stark_ab"]:
        ergebnis["urteil"] = "starkes Frühzeichen"
    elif veraenderung >= s["anstieg_ab"]:
        ergebnis["urteil"] = "Frühzeichen"
    else:
        ergebnis["urteil"] = "ruhig"
    return ergebnis


def _stuecke(start: date, ende: date, tage: int = 92) -> list[tuple[date, date]]:
    """Zeitraum in Stücke zu höchstens `tage` Tagen: kleine Abfragen antworten schnell."""
    stuecke, von = [], start
    while von <= ende:
        bis = min(von + timedelta(days=tage - 1), ende)
        stuecke.append((von, bis))
        von = bis + timedelta(days=1)
    return stuecke


def _rueckwaerts_pfad():
    return konfig.INLAND / "_rueckwaerts.json"


def aktualisiere(eintrag: dict, heute: date, s: dict, pause: float = 1.5, frist: float | None = None) -> list[dict]:
    """Holt, was im Archiv fehlt, und gibt die ganze Reihe zurück.

    PIHPS: zuerst die jüngsten Monate (Pflicht für das Frühzeichen), danach rückwärts die
    Geschichte bis `pihps_ab`, solange die Frist reicht. Wie weit zurück schon geholt ist,
    steht in daten/inland/_rueckwaerts.json; so geht es am nächsten Tag dort weiter.
    """
    pfad = archiv_pfad(eintrag["kennung"])
    vorhanden = speicher.lies_json(pfad, []) or []
    quelle = eintrag["quelle"]
    if quelle == "pihps":
        ware, preisart = eintrag["ware"], eintrag.get("preisart", 1)
        if vorhanden:
            start = date.fromisoformat(vorhanden[-1]["datum"]) - timedelta(days=30)
        else:
            start = heute - timedelta(days=s.get("pihps_erst_tage", 150))
        neu = []
        for nr, (von, bis) in enumerate(_stuecke(start, heute)):
            if nr:
                time.sleep(pause)
            neu += inland.hole_pihps(ware, preisart, von, bis)
        reihe = ergaenze(pfad, neu)
        ab = date.fromisoformat(str(s["pihps_ab"]))
        stand = speicher.lies_json(_rueckwaerts_pfad(), {}) or {}
        cursor = date.fromisoformat(stand.get(eintrag["kennung"], min(start, date.fromisoformat(reihe[0]["datum"])
                                                                       if reihe else start).isoformat()))
        while cursor > ab and (frist is None or time.monotonic() < frist):
            von = max(ab, cursor - timedelta(days=92))
            time.sleep(pause)
            teil = inland.hole_pihps(ware, preisart, von, cursor - timedelta(days=1))
            if teil:
                reihe = ergaenze(pfad, teil)
            cursor = von
            stand[eintrag["kennung"]] = cursor.isoformat()
            speicher.schreibe_json(_rueckwaerts_pfad(), stand)
        return reihe
    if quelle == "mpob":
        jahre = [heute.year]
        if not vorhanden or heute.month == 1:
            jahre.insert(0, heute.year - 1)
        neu = []
        for nr, jahr in enumerate(jahre):
            if nr:
                time.sleep(pause)
            try:
                neu += inland.hole_mpob(jahr)
            except inland.FormatFehler:
                # Frühere Jahre liefert die Seite zum Teil leer aus; nur das laufende Jahr ist Pflicht.
                if jahr == heute.year:
                    raise
        return ergaenze(pfad, neu)
    if quelle == "fpma":
        return ergaenze(pfad, inland.hole_fpma(eintrag["serie"]))
    raise ValueError(f"unbekannte Quelle {quelle}")


def rechne(k: dict, heute: date, zeitpunkt, holen: bool = True, frist: float | None = None) -> dict:
    s = k["schwellen"]["inlandspreise"]
    reihen = {}
    for kennung_r, r in k["rohstoffe"].items():
        for e in r.get("inlandspreise") or []:
            info = {"rohstoff": kennung_r, "name": e["name"], "land": e.get("land"), "quelle": e["quelle"],
                    "einheit": e.get("einheit"), "rolle": e.get("rolle", "fruehzeichen")}
            try:
                reihe = aktualisiere(e, heute, s, frist=frist) if holen else (speicher.lies_json(archiv_pfad(e["kennung"]), []) or [])
                info["status"] = "ok"
            except Exception as fehler:  # eine Quelle darf die anderen nicht mitreißen
                reihe = speicher.lies_json(archiv_pfad(e["kennung"]), []) or []
                info.update({"status": "Fehler", "meldung": f"{type(fehler).__name__}: {fehler}"[:300]})
            info["werte"] = len(reihe)
            info.update(fruehzeichen(reihe, heute, s))
            reihen[e["kennung"]] = info
    zeichen = [kz for kz, i in reihen.items()
               if i["rolle"] == "fruehzeichen" and i.get("urteil") in ("Frühzeichen", "starkes Frühzeichen")]
    return {"stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "version": __version__,
            "hinweis": HINWEIS, "reihen": reihen, "fruehzeichen": zeichen}


def status_text(e: dict) -> str:
    fehler = [i["name"] for i in e["reihen"].values() if i["status"] == "Fehler"]
    zustand = "Fehler" if e["reihen"] and len(fehler) == len(e["reihen"]) else ("Warnung" if fehler else "in Ordnung")
    zeilen = ["Agent: Inlandspreise (täglich, GitHub)",
              f"Stand: {e['stand'][8:10]}.{e['stand'][5:7]}.{e['stand'][:4]}, {e['stand'][11:16]}",
              f"Zustand: {zustand}",
              "Ergebnis: daten/inlandspreise.json, daten/inland/",
              f"Frühzeichen: {', '.join(e['fruehzeichen']) if e['fruehzeichen'] else 'keines'}"]
    for kennung, i in e["reihen"].items():
        zeilen.append(f"- {kennung}: {i['status']}, {i.get('werte', 0)} Werte, Urteil {i.get('urteil')}"
                      + (f", Veränderung {i['veraenderung']:+.1%}" if i.get("veraenderung") is not None else "")
                      + (f", {i['meldung']}" if i.get("meldung") else ""))
    return "\n".join(zeilen) + "\n"


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Inlandspreise als Frühzeichen")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    teiler.add_argument("--budget-minuten", type=float, default=10.0,
                        help="so lange wird höchstens die Geschichte nachgeholt")
    args = teiler.parse_args(argv)
    k = konfig.konfiguration()
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    heute = zeitpunkt.date()
    ergebnis = rechne(k, heute, zeitpunkt, frist=time.monotonic() + 60.0 * args.budget_minuten)
    speicher.schreibe_json(konfig.DATEN / "inlandspreise.json", ergebnis)
    text = status_text(ergebnis)
    speicher.schreibe_text(konfig.ABGABE / "status-inlandspreise.md", text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
