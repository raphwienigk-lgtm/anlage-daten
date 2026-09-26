"""Nachprüfer: wöchentliche Bilanz der echten Signale, gerechnet auf GitHub.

Er verstellt nichts selbst. Er rechnet aus Logbuch, Preisarchiven und letztem Stand:
- Laufkontrolle: an wie vielen der letzten sieben Tage der tägliche Lauf gelang
  (aus der Liste der GitHub-Läufe, die der Workflow übergibt)
- Ampel der Woche: aktuelle Farbe, seit wann, Farbwechsel der letzten sieben Tage
- Schattendepot: jede gedachte Position mit Einstieg, heutigem oder Schlusskurs,
  Veränderung, bestem und schlechtestem Stand seit dem Einstieg
- Signalbilanz am Rohstoffpreis mit denselben Regeln wie im Rückblick
- Vergleich mit dem Rückblick
- Vorschlag, die Regeln zu überprüfen, erst ab genug abgeschlossenen Signalen
- seit 26.09.2026 auch die anderen Zweige: Laufkontrolle der weiteren täglichen Workflows
  (Metall, Ersatz, Inlandspreise), Stufen der Woche aus ihrem Verlauf und das Schattendepot
  des Ersatz-Sensors. Rot und Schattendepot der Metalle führt der Metall-Wächter in der Cloud.

Mail-Vetos kennt er nicht (die liegen im Projekt); die ordnet der Nachprüfer in der
Cloud ein, der diesen Bericht abholt.

Schreibt daten/nachpruefer.json, abgabe/nachpruefer-teil-N.md, abgabe/status-nachpruefer.md.
Aufruf: python -m anlage.nachpruefer [--heute JJJJ-MM-TT] [--laeufe laeufe.json] [--laeufe-ordner ORDNER]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__, bilanz, konfig, logbuch, speicher
from .ausgabe import nachpruefer_text
from .quellen import kurse

HINWEIS = "Denkhilfe, keine Anlageberatung."


def _tag(zeit: str) -> date:
    return date.fromisoformat(zeit[:10])


def _berlin_tag(zeit: str) -> str:
    """Zeitstempel von GitHub (UTC) → Kalendertag in Berlin; der Metall-Lauf um 23:17 UTC gehört zum nächsten Tag."""
    try:
        return datetime.fromisoformat(zeit.replace("Z", "+00:00")).astimezone(konfig.ZEITZONE).date().isoformat()
    except ValueError:
        return zeit[:10]


# ------------------------------------------------------------------ Bausteine
def laufkontrolle(laeufe: list[dict] | None, heute: date, stand: dict | None,
                  betrieb_seit: date | None = None) -> dict:
    """laeufe: Ausgabe von `gh run list --json conclusion,createdAt` für den täglichen Lauf.

    Gezählt werden nur Tage ab `betrieb_seit` (erster geplanter Lauf); davor gab es
    den täglichen Lauf noch nicht, und das ist kein Ausfall.
    """
    ergebnis = {"stand_datum": (stand or {}).get("datum"), "zustand": (stand or {}).get("zustand"),
                "hinweise": (stand or {}).get("hinweise") or [],
                "betrieb_seit": betrieb_seit.isoformat() if betrieb_seit else None}
    if laeufe is None:
        return {**ergebnis, "tage_mit_lauf": None, "tage_gezaehlt": None, "fehlende_tage": None}
    tage = [heute - timedelta(days=k) for k in range(7)]
    if betrieb_seit:
        tage = [t for t in tage if t >= betrieb_seit]
    erfolgreich = {_berlin_tag(e["createdAt"]) for e in laeufe if e.get("conclusion") == "success"}
    fehlend = [t.isoformat() for t in tage if t.isoformat() not in erfolgreich]
    return {**ergebnis, "tage_mit_lauf": len(tage) - len(fehlend), "tage_gezaehlt": len(tage),
            "fehlende_tage": sorted(fehlend)}


def ampel_woche(eintraege: list[dict], kennung: str, heute: date) -> dict:
    eigene = [e for e in eintraege if e.get("rohstoff") == kennung]
    if not eigene:
        return {"farbe": None, "seit": None, "wechsel": []}
    letzter = eigene[-1]
    grenze = heute - timedelta(days=6)
    wechsel = [{"tag": e["zeit"][:10], "vorher": e.get("vorher"), "farbe": e["farbe"], "anlass": e.get("anlass"),
                "gesperrt": e.get("gesperrt")}
               for e in eigene if _tag(e["zeit"]) >= grenze]
    return {"farbe": letzter["farbe"], "zahl": letzter.get("zahl"), "gesperrt": letzter.get("gesperrt"),
            "seit": letzter["zeit"][:10], "wechsel": wechsel}


def _spanne(reihe: list[dict], von: str, bis: str | None) -> list[dict]:
    return [e for e in reihe if e["datum"] >= von and (bis is None or e["datum"] <= bis)]


def position(signal: dict, archive: dict[str, list[dict]], rohstoffreihe: list[dict] | None, heute: date,
             namen: dict[str, str] | None = None) -> dict:
    """Eine gedachte Position aus dem Logbuch, bewertet mit den Preisarchiven."""
    einstieg_tag = signal["zeit"][:10]
    schluss_tag = signal["schluss_zeit"][:10] if signal.get("schluss_zeit") else None
    werte = []
    for ticker, einstieg in (signal.get("kurse") or {}).items():
        reihe = archive.get(ticker) or []
        kurs0 = einstieg.get("kurs")
        eintrag = {"ticker": ticker, "name": (namen or {}).get(ticker, ticker), "einstieg": kurs0,
                   "einstieg_datum": einstieg.get("datum")}
        if not kurs0:
            werte.append({**eintrag, "status": "ohne Einstiegskurs"})
            continue
        if schluss_tag and (signal.get("schluss_kurse") or {}).get(ticker, {}).get("kurs"):
            ende = signal["schluss_kurse"][ticker]
            eintrag.update({"ende": ende["kurs"], "ende_datum": ende.get("datum"), "art": "Schluss"})
        else:
            danach = _spanne(reihe, einstieg.get("datum") or einstieg_tag, schluss_tag)
            if not danach:
                werte.append({**eintrag, "status": "keine Kurse seit dem Einstieg"})
                continue
            eintrag.update({"ende": danach[-1]["schluss"], "ende_datum": danach[-1]["datum"],
                            "art": "Schluss" if schluss_tag else "heute"})
        verlauf = [e["schluss"] for e in _spanne(reihe, einstieg.get("datum") or einstieg_tag,
                                                 eintrag["ende_datum"])] or [eintrag["ende"]]
        eintrag.update({
            "status": "ok",
            "veraenderung": round(eintrag["ende"] / kurs0 - 1, 4),
            "hoechster": round(max(verlauf) / kurs0 - 1, 4),
            "tiefster": round(min(verlauf) / kurs0 - 1, 4),
        })
        werte.append(eintrag)
    rohstoff = None
    preis0 = (signal.get("rohstoffpreis") or {}).get("wert")
    if preis0:
        preis1 = ((signal.get("schluss_rohstoffpreis") or {}).get("wert") if schluss_tag
                  else (rohstoffreihe or [{}])[-1].get("wert"))
        datum1 = ((signal.get("schluss_rohstoffpreis") or {}).get("datum") if schluss_tag
                  else (rohstoffreihe or [{}])[-1].get("datum"))
        if preis1:
            rohstoff = {"einstieg": preis0, "einstieg_monat": (signal["rohstoffpreis"].get("datum") or "")[:7],
                        "ende": preis1, "ende_monat": (datum1 or "")[:7], "veraenderung": round(preis1 / preis0 - 1, 4)}
    tage = (date.fromisoformat(schluss_tag) if schluss_tag else heute) - date.fromisoformat(einstieg_tag)
    return {"seit": einstieg_tag, "bis": schluss_tag, "offen": schluss_tag is None, "zahl": signal.get("zahl"),
            "tage": tage.days, "instrumente": werte, "rohstoff": rohstoff}


def rueckblick_vergleich(kennung: str) -> dict | None:
    e = speicher.lies_json(konfig.RUECKBLICK / f"{kennung}.json")
    try:
        b = e["lernzeit"]["bilanz"]
        return {"stand": e["stand"][:10], "bestanden": b["urteil"]["bestanden"], "anzahl": b["anzahl"],
                "treffer": b["treffer"], "fehlalarme": b["fehlalarme"], "mittel_12": b["mittel_12"],
                "basis_12": b["basis_12"], "von": b["von"], "bis": b["bis"]}
    except (TypeError, KeyError):
        return None


def _datum_oder_none(wert) -> date | None:
    if not wert:
        return None
    return wert if isinstance(wert, date) else date.fromisoformat(str(wert))


def weitere_laeufe(liste: list[dict], ordner: str | None, heute: date) -> list[dict]:
    """Laufkontrolle der anderen täglichen Workflows; je Workflow eine Datei <workflow>.json im Ordner."""
    ergebnis = []
    for w in liste or []:
        laeufe = None
        if ordner:
            pfad = Path(ordner) / f"{w['workflow']}.json"
            try:
                laeufe = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else None
            except (OSError, json.JSONDecodeError):
                laeufe = None
        lk = laufkontrolle(laeufe, heute, None, _datum_oder_none(w.get("betrieb_seit")))
        ergebnis.append({"workflow": w["workflow"], "name": w["name"],
                         **{k: lk[k] for k in ("betrieb_seit", "tage_mit_lauf", "tage_gezaehlt", "fehlende_tage")}})
    return ergebnis


def woche(verlauf: list[dict], heute: date, wert) -> dict:
    """Stand, seit wann, und Wechsel der letzten sieben Tage aus einem Verlauf mit einer Zeile je Lauf."""
    eintraege = [e for e in verlauf if wert(e) is not None]
    if not eintraege:
        return {"jetzt": None, "seit": None, "seit_beginn": False, "wechsel": []}
    jetzt = wert(eintraege[-1])
    seit = eintraege[-1]["datum"]
    for e in reversed(eintraege):
        if wert(e) != jetzt:
            break
        seit = e["datum"]
    grenze = (heute - timedelta(days=6)).isoformat()
    wechsel = [{"tag": b["datum"], "vorher": wert(a), "jetzt": wert(b)}
               for a, b in zip(eintraege, eintraege[1:]) if wert(a) != wert(b) and b["datum"] >= grenze]
    return {"jetzt": jetzt, "seit": seit, "seit_beginn": seit == eintraege[0]["datum"], "wechsel": wechsel}


def zweige(heute: date) -> dict:
    """Metall-Datenteile und Ersatz-Sensoren: Stufen der Woche, beim Ersatz dazu das Schattendepot."""
    ergebnis = {}
    for pfad in sorted((konfig.KONFIG / "metalle").glob("*.yaml")):
        k = konfig.lade_yaml(pfad)
        verlauf = logbuch.lies(konfig.DATEN / "metall" / k["kennung"] / "verlauf.jsonl")
        ergebnis[f"metall_{k['kennung']}"] = {
            "art": "metall", "name": f"Metall {k['name']}", "laeufe": len(verlauf),
            "achsen": {a: {"name": k["achsen"][a]["name"],
                           **woche(verlauf, heute, lambda e, a=a: (e.get("stufen") or {}).get(a))}
                       for a in k["achsen"]}}
    for pfad in sorted((konfig.KONFIG / "ersatz").glob("*.yaml")):
        k = konfig.lade_yaml(pfad)
        o = konfig.DATEN / "ersatz" / k["kennung"]
        verlauf = logbuch.lies(o / "verlauf.jsonl")
        depot = speicher.lies_json(o / "schattendepot.json", None) or {"positionen": []}
        ticker = [e["ticker"] for e in k["ersatz"]] + [k["vergleich"]["ticker"]]
        archive = {t: kurse.lies_archiv(kurse.archiv_pfad(o / "kurse", t)) for t in ticker}
        namen = {e["ticker"]: e["name"] for e in k["ersatz"]}
        positionen = []
        for sig in depot["positionen"]:
            pos = position(sig, archive, None, heute, namen)
            ref0 = next(iter((sig.get("vergleich") or {}).values()), None)
            ref1 = next(iter((sig.get("schluss_vergleich") or {}).values()), None)
            reihe = archive.get(k["vergleich"]["ticker"]) or []
            ende = ref1["kurs"] if ref1 else (reihe[-1]["schluss"] if reihe else None)
            pos["vergleich"] = (round(ende / ref0["kurs"] - 1, 4) if ref0 and ref0.get("kurs") and ende else None)
            pos["grund"] = sig.get("schluss_grund")
            positionen.append(pos)
        ergebnis[f"ersatz_{k['kennung']}"] = {
            "art": "ersatz", "name": f"Ersatz-Sensor {k['name']}", "laeufe": len(verlauf),
            "vergleich": k["vergleich"]["name"],
            **woche(verlauf, heute, lambda e: e.get("stufe")), "positionen": positionen}
    return ergebnis


def _betrieb_seit(s: dict) -> date | None:
    wert = (s.get("nachpruefer") or {}).get("betrieb_seit")
    if not wert:
        return None
    return wert if isinstance(wert, date) else date.fromisoformat(str(wert))


# ------------------------------------------------------------------ Gesamt
def nachpruefung(k: dict, heute: date, laeufe: list[dict] | None, zeitpunkt: datetime,
                 laeufe_ordner: str | None = None) -> dict:
    eintraege = logbuch.lies(konfig.DATEN / "signale.jsonl")
    stand = speicher.lies_json(konfig.DATEN / "stand.json")
    s = k["schwellen"]
    s_rb = s["rueckblick"]
    mindest = (s.get("nachpruefer") or {}).get("mindest_signale_fuer_vorschlag", 5)
    namen = {i["ticker"]: i.get("name", i["ticker"]) for r in k["rohstoffe"].values() for i in r.get("instrumente", [])}
    tickers = set(namen)
    archive = {t: kurse.lies_archiv(kurse.archiv_pfad(konfig.PREISE, t)) for t in sorted(tickers)}
    rohstoffe = {}
    for kennung, r in k["rohstoffe"].items():
        if r.get("rolle") == "verworfen":
            continue
        preis = r.get("preis") or {}
        reihe = (speicher.lies_json(konfig.PREISE / f"fred_{preis.get('serie')}.json")
                 if preis.get("quelle") == "fred" else None) or []
        signale = bilanz.signale_aus_logbuch(eintraege, kennung)
        bewertet = [bilanz.bewerte_signal(sig, bilanz.preis_nach_monat(reihe), s_rb["treffer_ab"]) for sig in signale]
        auswertbar = [b for b in bewertet if b["urteil"] != "offen"]
        rohstoffe[kennung] = {
            "name": r["name"],
            "ampel": ampel_woche(eintraege, kennung, heute),
            "positionen": [position(sig, archive, reihe, heute, namen) for sig in signale],
            "signale": {"anzahl": len(bewertet), "treffer": sum(b["urteil"] == "Treffer" for b in bewertet),
                        "fehlalarme": sum(b["urteil"] == "Fehlalarm" for b in bewertet),
                        "offen": sum(b["urteil"] == "offen" for b in bewertet), "liste": bewertet},
            "rueckblick": rueckblick_vergleich(kennung),
            "vorschlag_faellig": len(auswertbar) >= mindest,
            "mindest_signale": mindest,
        }
    return {
        "stand": zeitpunkt.isoformat(timespec="seconds"),
        "version": __version__,
        "hinweis": HINWEIS,
        "woche": {"von": (heute - timedelta(days=6)).isoformat(), "bis": heute.isoformat()},
        "laufkontrolle": laufkontrolle(laeufe, heute, stand, _betrieb_seit(s)),
        "weitere_laeufe": weitere_laeufe((s.get("nachpruefer") or {}).get("weitere_laeufe"), laeufe_ordner, heute),
        "rohstoffe": rohstoffe,
        "zweige": zweige(heute),
    }


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Nachprüfer: wöchentliche Bilanz der echten Signale")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    teiler.add_argument("--laeufe", help="JSON-Datei aus gh run list für den täglichen Lauf")
    teiler.add_argument("--laeufe-ordner", help="Ordner mit <workflow>.json für die weiteren täglichen Läufe")
    args = teiler.parse_args(argv)
    k = konfig.konfiguration()
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    laeufe = None
    if args.laeufe and os.path.exists(args.laeufe):
        try:
            with open(args.laeufe, encoding="utf-8") as f:
                laeufe = json.load(f)
        except (OSError, json.JSONDecodeError):
            laeufe = None
    ergebnis = nachpruefung(k, zeitpunkt.date(), laeufe, zeitpunkt, args.laeufe_ordner)
    speicher.schreibe_json(konfig.DATEN / "nachpruefer.json", ergebnis)
    nachpruefer_text.schreibe(ergebnis, konfig.ABGABE)
    text = nachpruefer_text.zusammenfassung(ergebnis)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
