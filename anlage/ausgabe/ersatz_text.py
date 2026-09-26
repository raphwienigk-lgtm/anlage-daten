"""Vorlesetext eines Ersatz-Sensors (Haselnuss → Select Harvests). Zahlen ausgeschrieben, keine Tabellen."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen
from .metall_text import _datum, _punkte, _umsatz, _veraendert

WOCHENTAGE = vorlesen.WOCHENTAGE


def _vergleich(stand: dict) -> str:
    v = stand["vergleich"]
    return v.get("akkusativ") or f"den Vergleich {v['name']}"


def _grad(x: float) -> str:
    return f"{sprache.komma(x, 1)} Grad"


def _orte(stand: dict, kennungen: list[str]) -> str:
    namen = stand.get("standorte") or {}
    return sprache.aufzaehlung([namen.get(k, k).split(" (")[0] for k in kennungen])


def _jahre(liste: list[int]) -> str:
    return sprache.aufzaehlung([sprache.jahr(j) for j in liste])


def _stufe(stand: dict) -> str:
    teile = []
    w = stand.get("wechsel")
    if w:
        teile.append(f"Neu seit dem letzten Lauf: Die Stufe ist von {w['vorher']} auf {w['jetzt']} gesprungen.")
    satz = f"Stufe {stand['stufe']}."
    for g in stand["gruende"]:
        if g["art"] == "außer Saison":
            s = stand["saison"]
            satz += (f" Außer Saison: Die Spätfrost-Saison läuft vom {_datum(s['von'])} bis zum {_datum(s['bis'])}; "
                     f"Frostvorhersagen zählen ab dem {_datum(s['vorwarnung_ab'])}.")
        elif g["art"] == "vorhergesagt":
            nacht = "eine Frostnacht" if g["naechte"] == 1 else f"{sprache.wort(g['naechte'])} Frostnächte"
            satz += (f" Vorhergesagt ist {nacht}, die erste am {_datum(g['datum'])} in {_orte(stand, g['orte'])}, "
                     f"bis {_grad(g['tiefste'])}.")
        elif g["art"] == "gemessen":
            nacht = "eine Frostnacht" if g["naechte"] == 1 else f"{sprache.wort(g['naechte'])} Frostnächte"
            satz += (f" In dieser Saison gab es bisher {nacht}, die erste am {_datum(g['datum'])}, "
                     f"am kältesten {_grad(g['tiefste'])}" + (", darunter starker Frost." if g["stark"] else "."))
        elif g["art"] == "rot_gesperrt":
            satz += f" Rot bleibt gesperrt: {g['grund']}."
        elif g["art"] == "frostjahr":
            nacht = "einer Frostnacht" if g["naechte"] == 1 else f"{sprache.wort(g['naechte'])} Frostnächten"
            satz += (f" Die Saison {sprache.jahr(g['jahr'])} brachte {g['urteil']} mit {nacht}, am kältesten "
                     f"{_grad(g['tiefste'])}. Bis zum Ende der Ernte am dreißigsten September bleibt die Stufe auf Gelb.")
    if stand["stufe"] == "Rot":
        satz += " Starker Frost ist gemessen, der Rückblick bestanden und der Markt schläft. Das ist ein Signal zum Nachdenken, kein Kaufauftrag."
    teile.append(satz)
    return " ".join(teile)


def _sensor(stand: dict) -> str:
    sw = stand["schwellen"]
    orte = _orte(stand, list(stand["standorte"]))
    return (f"Gemessen wird an {sprache.wort(len(stand['standorte']))} Anbauorten: {orte}, umgerechnet auf die Höhe "
            f"der Obstgärten. Frost heißt {_grad(sw['frost_c'])} oder kälter an mindestens "
            f"{sprache.wort(sw['mindest_standorte'])} Orten in derselben Nacht, stark ab {_grad(sw['stark_c'])}.")


def _saisons(stand: dict) -> str:
    g = stand["saisons_geladen"]
    a = stand["abgleich"]
    if g["geladen"] < g["von"]:
        satz = (f"Die Frostsaisons ab neunzehnhunderteinundneunzig werden noch geladen, bisher "
                f"{sprache.wort(g['geladen'])} von {sprache.wort(g['von'])} Jahren.")
        if not g["geladen"]:
            return satz
    else:
        satz = ""
    erkannt = a["erkannte_jahre"]
    satz += (f" Rückblick auf die Frostsaisons: Der Sensor meldet Spätfrost in {sprache.wort(len(erkannt))} von "
             f"{sprache.wort(a['jahre_geprueft'])} Jahren" + (f": {_jahre(erkannt)}." if erkannt else "."))
    if a["bekannte_getroffen"] or a["bekannte_verfehlt"]:
        satz += " Von den belegten Frostjahren erkennt er "
        satz += _jahre(a["bekannte_getroffen"]) if a["bekannte_getroffen"] else "keines"
        if a["bekannte_verfehlt"]:
            satz += f"; verfehlt: {_jahre(a['bekannte_verfehlt'])}"
        satz += "."
    ls = stand.get("letzte_saison")
    if ls:
        satz += (f" Letzte Saison, {sprache.jahr(ls['jahr'])}: {ls['urteil']}, am kältesten "
                 + (_grad(ls["tiefste"]) if ls.get("tiefste") is not None else "ohne Wert") + ".")
    return satz.strip()


def _rueckblick(stand: dict) -> str:
    teile = []
    for t, r in stand["rueckblick"].items():
        z = r["zusammen"]
        h = r["haupt"]
        if not z["n"]:
            teile.append(f"{r['name']}: noch keine auswertbaren Frostjahre mit Kursen.")
            continue
        fall = "einem Frostjahr" if z["n"] == 1 else f"{sprache.wort(z['n'])} Frostjahren"
        satz = (f"{r['name']} nach {fall}, gerechnet ab dem Tag nach der ersten Frostnacht: nach "
                f"{sprache.wort(h)} Handelstagen im Mittel {_punkte(z[f'v{h}'])} gegen {_vergleich(stand)}")
        weitere = [f"nach {sprache.wort(x)} {_punkte(z[f'v{x}'])}" for x in (20, 120) if z.get(f"v{x}") is not None and x != h]
        if weitere:
            satz += ", " + ", ".join(weitere)
        satz += "; " + {0: "in keinem Fall ein Treffer", 1: "Treffer in einem Fall"}.get(
            z["treffer"], f"Treffer in {sprache.wort(z['treffer'])} Fällen") + "."
        satz += {"bestanden": " Nach der vorläufigen Regel bestanden.",
                 "nicht bestanden": " Nach der vorläufigen Regel nicht bestanden.",
                 "zu wenige Fälle": " Zu wenige Fälle für ein Urteil."}[r["urteil"]]
        teile.append(satz)
    return " ".join(teile)


def _preise(stand: dict) -> str:
    teile = []
    for p in stand["preise"].values():
        if p["urteil"] == "keine Kurse":
            teile.append(f"{p['name']}: keine Kurse.")
            continue
        satz = p["name"]
        if p.get("r_kurz") is not None:
            satz += f" ist in fünf Handelstagen {_veraendert(p['r_kurz'])}"
        if p.get("r_lang") is not None:
            satz += f", in zwanzig {_veraendert(p['r_lang'])}"
        if p.get("vorsprung_lang") is not None:
            satz += f", gegen {_vergleich(stand)} {_punkte(p['vorsprung_lang'])}"
        satz += "."
        if p.get("handel"):
            satz += f" Umsatz zuletzt {_umsatz(p['handel'], p.get('waehrung', 'USD'))} am Tag"
            satz += ", das ist dünn." if p.get("duenn") else "."
        satz += {"schläft": " Der Markt schläft noch.", "gelaufen": " Der Kurs ist schon gelaufen."}.get(p["urteil"], "")
        teile.append(satz)
    return "Preisprobe. " + " ".join(teile)


def _quellen(stand: dict) -> str:
    kaputt = [k for k, q in stand["quellen"].items() if q.get("status") == "Fehler"]
    halb = [k for k, q in stand["quellen"].items() if q.get("status") == "Warnung"]
    namen = {"openmeteo": "Open-Meteo-Archiv", "openmeteo_vorhersage": "Open-Meteo-Vorhersage", "yahoo": "Kurse von Yahoo"}
    if not kaputt and not halb:
        return "Alle Quellen waren erreichbar."
    satz = ""
    if kaputt:
        satz += "Nicht erreichbar: " + ", ".join(namen.get(k, k) for k in kaputt) + "."
    if halb:
        satz += (" " if satz else "") + "Nur teilweise erreichbar: " + ", ".join(namen.get(k, k) for k in halb) + "."
    return satz


def absaetze(stand: dict) -> list[str]:
    heute = date.fromisoformat(stand["datum"])
    ersatz = stand["ersatz"][0]
    liste = [f"Der Ersatz-Sensor {stand['name']}, Datenteil für {WOCHENTAGE[heute.weekday()]}, den {sprache.datum(heute)}. "
             f"Der Sensor schlägt beim Original aus, gekauft würde der Ersatz: {ersatz['name']}, {ersatz.get('hinweis', '')}. "
             f"Das Original, {stand['original']['name']}, ist nicht handelbar: {stand['original']['hinweis']}.",
             _stufe(stand), _sensor(stand), _saisons(stand), _rueckblick(stand), _preise(stand), _quellen(stand),
             ("Der Rückblick ist bestanden; ob der Sensor zum Kandidaten wird, entscheidest du. "
              if any(r["urteil"] == "bestanden" for r in stand["rueckblick"].values())
              else "Der Sensor bleibt Sensor, bis sein Rückblick bestanden ist. ")
             + "Das ist eine Denkhilfe, keine Anlageberatung."]
    return [sprache.ausschreiben(a) for a in liste if a]


def schreibe(stand: dict, ordner: Path) -> list[Path]:
    zeit = datetime.fromisoformat(stand["stand"])
    praefix = f"ersatz-{stand['kennung']}"
    stuecke = vorlesen.aufteilen(absaetze(stand), vorlesen.stempel(zeit))
    pfade = vorlesen.schreibe_teile(ordner, praefix, stuecke)
    ergebnis = (f"abgabe/{praefix}-teil-1.md" if len(stuecke) == 1
                else f"abgabe/{praefix}-teil-1.md bis {praefix}-teil-{len(stuecke)}.md")
    status = (f"Agent: Ersatz-Sensor {stand['name']} (Datenlauf auf GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {stand['zustand']}\n"
              f"Ergebnis: {ergebnis}, daten/ersatz/{stand['kennung']}/stand.json\n"
              f"Stufe: {stand['stufe']} ({stand['phase']})\n"
              + vorlesen.umfang_zeile(stuecke))
    speicher.schreibe_text(ordner / f"status-{praefix}.md", status)
    return pfade


def zusammenfassung(stand: dict) -> str:
    zeilen = [f"## Ersatz {stand['kennung']}, {stand['stand']}, Zustand {stand['zustand']}", "",
              f"- Stufe {stand['stufe']} ({stand['phase']}), Gründe {stand['gruende']}",
              f"- Saisons geladen {stand['saisons_geladen']}", f"- Abgleich {stand['abgleich']}"]
    for s in stand["saisons"]:
        if s["urteil"] != "ruhig" or s["jahr"] in (2004, 2014, 2025):
            zeilen.append(f"  - {s['jahr']}: {s['urteil']}, {s['frostnaechte']} Nächte, erste {s['erste']}, tiefste {s['tiefste']}")
    for t, p in stand["preise"].items():
        zeilen.append(f"- {t}: {p['urteil']}, r5 {p.get('r_kurz')}, r20 {p.get('r_lang')}, v20 {p.get('vorsprung_lang')}, "
                      f"Handel {p.get('handel')}")
    for t, r in stand["rueckblick"].items():
        zeilen.append(f"- Rückblick {t}: {r['urteil']} {r['zusammen']}")
    for k, q in stand["quellen"].items():
        zeilen.append(f"- Quelle {k}: {q.get('status')} {q.get('meldung') or ''}")
    return "\n".join(zeilen) + "\n"
