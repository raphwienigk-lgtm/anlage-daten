"""Vorlesetext zur Frage, welche Aktie dem Rohstoffpreis am engsten folgt. Nur Messwerte."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen


def _monat(text: str) -> str:
    return sprache.monat(int(text[:4]), int(text[5:7]))


def _pm(anteil: float) -> str:
    p = round(anteil * 100)
    if p == 0:
        return "kaum verändert"
    zahl = "ein" if abs(p) == 1 else sprache.wort(abs(p))
    return f"um {zahl} Prozent {'gestiegen' if p > 0 else 'gefallen'}"


def _korrelation(x: float) -> str:
    return sprache.komma(x, 2)


def _umsatz(betrag: float | None) -> str | None:
    if not betrag:
        return None
    if betrag >= 1_000_000:
        millionen = round(betrag / 1_000_000, 1)
        return f"rund {sprache.komma(millionen, 1)} Millionen Singapur-Dollar"
    return f"rund {sprache.wort(round(betrag, -3))} Singapur-Dollar"


def _aktie(e: dict) -> str:
    kopf = e["name"] + (f" ({e['hinweis']})" if e.get("hinweis") else "")
    if e.get("status") == "Fehler":
        return f"{kopf}: Die Kurse waren diesmal nicht abrufbar."
    if e.get("status") != "ok":
        return f"{kopf}: Die gemeinsame Reihe ist noch zu kurz für einen Vergleich."
    satz = (f"{kopf}: gemeinsame Monate von {_monat(e['von'])} bis {_monat(e['bis'])}. "
            f"Über zwölf Monate gerechnet liegt die Korrelation mit dem Rohstoffpreis bei {_korrelation(e['korrelation_12'])}")
    if e.get("korrelation_1") is not None:
        satz += f", von Monat zu Monat bei {_korrelation(e['korrelation_1'])}"
    satz += "."
    if e.get("mitnahme") is not None:
        mit = e["mitnahme"] * 10
        satz += (f" Stieg der Rohstoff in zwölf Monaten um zehn Prozent, war die Aktie im Mittel "
                 f"{_pm(mit / 100)}.")
    if e.get("stark_spannen"):
        satz += (f" In den Zwölf-Monats-Spannen mit einem Anstieg des Rohstoffs um mindestens zwanzig Prozent "
                 f"war die Aktie im Mittel {_pm(e['stark_mittel'])}, über alle Spannen {_pm(e['alle_mittel'])}.")
    umsatz = _umsatz(e.get("handel"))
    if umsatz:
        satz += f" Gehandelt wurden zuletzt im Mittel {umsatz} am Tag."
    return satz


def absaetze(ergebnis: dict) -> list[str]:
    liste = ["Welche Aktie folgt dem Rohstoffpreis am engsten? Hier stehen nur Messwerte, keine Empfehlung. "
             "Eine Korrelation von eins hieße: Die Aktie bewegt sich genau mit dem Preis; null hieße: kein Zusammenhang. "
             "Die Kurse sind in Singapur-Dollar, der Rohstoffpreis in US-Dollar."]
    for r in ergebnis["rohstoffe"].values():
        liste.append(f"{r['name']}, Preis bis {_monat(r['rohstoff_bis'])}." if r.get("rohstoff_bis") else r["name"] + ".")
        for e in r["aktien"]:
            liste.append(_aktie(e))
        namen = {e["ticker"]: e["name"] for e in r["aktien"]}
        if len(r["reihenfolge"]) > 1:
            liste.append("Nach der Korrelation über zwölf Monate folgt am engsten "
                         + ", dann ".join(namen[t] for t in r["reihenfolge"])
                         + ". Wie gut sich eine Aktie handeln lässt, steht beim Tagesumsatz.")
    liste.append("Das ist eine Denkhilfe, keine Anlageberatung.")
    return liste


def schreibe(ergebnis: dict, ordner: Path) -> list[Path]:
    zeit = datetime.fromisoformat(ergebnis["stand"])
    stuecke = vorlesen.aufteilen(absaetze(ergebnis), vorlesen.stempel(zeit))
    pfade = vorlesen.schreibe_teile(ordner, "aktienbezug", stuecke)
    fehler = [e["ticker"] for r in ergebnis["rohstoffe"].values() for e in r["aktien"] if e.get("status") != "ok"]
    alle = [e for r in ergebnis["rohstoffe"].values() for e in r["aktien"]]
    zustand = "Fehler" if alle and len(fehler) == len(alle) else ("Warnung" if fehler else "in Ordnung")
    status = (f"Agent: Aktienbezug (von Hand, GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {zustand}\n"
              f"Ergebnis: abgabe/aktienbezug-teil-1.md, daten/aktienbezug.json\n"
              + (f"Ohne Vergleich: {', '.join(fehler)}\n" if fehler else "")
              + vorlesen.umfang_zeile(stuecke))
    speicher.schreibe_text(ordner / "status-aktienbezug.md", status)
    return pfade


def zusammenfassung(ergebnis: dict) -> str:
    zeilen = [f"## Aktienbezug, {ergebnis['stand']}", ""]
    for kennung, r in ergebnis["rohstoffe"].items():
        zeilen.append(f"- {kennung}: Reihenfolge {r['reihenfolge']}")
        for e in r["aktien"]:
            zeilen.append(f"  - {e['ticker']}: {e.get('status')}, k12 {e.get('korrelation_12')}, k1 {e.get('korrelation_1')}, "
                          f"Mitnahme {e.get('mitnahme')}, stark {e.get('stark_mittel')} ({e.get('stark_spannen')}), "
                          f"alle {e.get('alle_mittel')}, Handel {e.get('handel')}, {e.get('von')}–{e.get('bis')}"
                          + (f", {e.get('meldung')}" if e.get("meldung") else ""))
    return "\n".join(zeilen) + "\n"
