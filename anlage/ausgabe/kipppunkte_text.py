"""Vorlesetext des Kipppunkt-Registers (Wächter 3), im gemeinsamen Vorlese-Format.

Nur Messwerte und Trends, keine Bewertung: Bewertet wird gemeinsam im Quartal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen

QUARTALE = {"Q1": "erste", "Q2": "zweite", "Q3": "dritte", "Q4": "vierte"}


def _j(n) -> str:
    return sprache.jahr(int(n))


def _spanne(von, bis) -> str:
    return f"{_j(von)} bis {_j(bis)}"


def _monat(text: str) -> str:
    return sprache.monat(int(text[:4]), int(text[5:7]))


def _grad(x: float, stellen: int = 1) -> str:
    wert = sprache.komma(abs(x), stellen)
    return f"{wert} Grad"


def _rund(n: float) -> str:
    """Große Zahlen auf Tausender: 140346 → „rund hundertvierzigtausend“."""
    if n >= 10000:
        return "rund " + sprache.wort(round(n, -3))
    return sprache.wort(round(n))


def _trend(x: float | None, einheit: str, stellen: int = 1) -> str:
    if x is None:
        return "Einen Trend geben die Daten noch nicht her."
    if round(x, stellen) == 0:
        return "Über die letzten dreißig Jahre ist kein Trend zu erkennen."
    richtung = "zu" if x > 0 else "ab"
    return f"Über die letzten dreißig Jahre nimmt der Wert um {_menge(abs(x), stellen)} {einheit} je Jahrzehnt {richtung}."


def _menge(x: float, stellen: int) -> str:
    """Wie sprache.komma, aber „ein“ statt „eins“ vor einer Einheit."""
    text = sprache.komma(x, stellen)
    return "ein" if text == "eins" else text


def _geschlecht(n: int, eine: str = "eine", keine: str = "keine") -> str:
    """Anzahl vor einem weggelassenen Hauptwort: „eine“, „keine“, „zwei“."""
    return keine if n == 0 else eine if n == 1 else sprache.wort(n)


def _kopf(e: dict) -> str:
    return f"{e['name']}. Kipppunkt: {e['kipppunkt']}. Betrifft {e['region']}."


def _fehler(name: str) -> str:
    return f"{name}: Diesmal fehlen die Daten, die Quelle war nicht erreichbar oder hat ihr Format geändert."


# ------------------------------------------------------------------ Bausteine
def _kaltfleck(e: dict, ref: tuple[int, int]) -> str:
    satz = _kopf(e)
    s = e.get("schere_letzte_5")
    if s is not None and e.get("bis_jahr"):
        lage = "kühler" if s < 0 else "wärmer"
        satz += (f" Gemessen am Weltozean war das Meer dort in den fünf Jahren bis {_j(e['bis_jahr'])} "
                 f"{_grad(s, 2)} {lage} als in der Vergleichszeit {_spanne(*ref)}.")
    m = e.get("meer_letzte_5")
    if m is not None:
        satz += f" Für sich allein betrachtet lag es {_grad(m, 2)} {'unter' if m < 0 else 'über'} der Vergleichszeit."
    t = e.get("trend_30")
    if t is not None:
        if round(t, 2) == 0:
            satz += " Gegenüber dem Weltozean ist über die letzten dreißig Jahre kein Trend zu erkennen."
        else:
            satz += (f" Über die letzten dreißig Jahre wird es dort gegenüber dem Weltozean um "
                     f"{_grad(t, 2)} je Jahrzehnt {'wärmer' if t > 0 else 'kühler'}.").replace("um eins Grad", "um ein Grad")
    jetzt, frueher = e.get("traegheit_jetzt"), e.get("traegheit_frueher")
    if jetzt and frueher and jetzt.get("ac1") is not None and frueher.get("ac1") is not None:
        satz += (f" Die Trägheit der Reihe nach Abzug des Trends liegt in den letzten dreißig Jahren bei "
                 f"{sprache.komma(jetzt['ac1'], 2)}, in den dreißig Jahren davor bei {sprache.komma(frueher['ac1'], 2)}."
                 " Steigende Trägheit gilt in der Forschung als mögliches Frühzeichen eines Kipppunkts.")
    if e.get("letzter_monat"):
        satz += f" Letzter Monatswert: {_monat(e['letzter_monat'])}."
    return satz


def _amoc(e: dict) -> str:
    satz = _kopf(e)
    satz += (f" Die Messkette misst seit {_monat(e['erster_monat'])}; ein Sverdrup ist eine Million "
             "Kubikmeter Wasser je Sekunde.")
    if e.get("anfang_4_jahre") is not None:
        satz += f" In den ersten vier Jahren lag die Strömung im Mittel bei {sprache.komma(e['anfang_4_jahre'], 1)} Sverdrup"
        if e.get("letzte_12_monate") is not None:
            satz += (f", in den letzten zwölf Monaten bis {_monat(e['letzter_monat'])} bei "
                     f"{sprache.komma(e['letzte_12_monate'], 1)} Sverdrup")
        satz += "."
    satz += " " + _trend(e.get("trend_je_jahrzehnt"), "Sverdrup", 1).replace(
        "Über die letzten dreißig Jahre", "Über die ganze Reihe").replace("der Wert", "die Strömung")
    satz += " Die Messkette veröffentlicht mit ein bis zwei Jahren Verzögerung."
    return satz


def _el_nino(e: dict, stark_ab: float, sehr_stark_ab: float) -> str:
    satz = _kopf(e)
    stuecke = []
    for f in e.get("fenster") or []:
        stuecke.append(f"{'Von' if not stuecke else 'von'} {_spanne(f['von'], f['bis'])} "
                       f"{'gab es ' if not stuecke else ''}{_anzahl(f['episoden'], 'Episode', 'Episoden')}, davon "
                       f"{_geschlecht(f['stark'])} stark und {_geschlecht(f['sehr_stark'])} sehr stark")
    if stuecke:
        satz += (f" Gezählt nach dem Höhepunkt; stark heißt ab {sprache.komma(stark_ab, 1)} Grad über normal, "
                 f"sehr stark ab {sprache.komma(sehr_stark_ab, 1)} Grad. " + "; ".join(stuecke) + ".")
    staerkste = e.get("staerkste") or []
    if staerkste:
        satz += " Die stärksten seit neunzehnhundertfünfzig: " + sprache.aufzaehlung(
            [f"{_j(s['jahr'])} mit {sprache.komma(s['wert'], 1)} Grad" for s in staerkste[:3]]) + "."
    lauf = e.get("laufend")
    if lauf:
        satz += (f" Derzeit läuft eine Episode seit {sprache.jahreszeit(lauf['beginn']['jahreszeit'], lauf['beginn']['jahr'])},"
                 f" bisheriger Höchstwert {sprache.komma(lauf['hoehepunkt']['wert'], 1)}.")
    return satz


def _anzahl(n: int, einzahl: str, mehrzahl: str) -> str:
    if n == 0:
        return f"keine {mehrzahl}"
    if n == 1:
        return f"eine {einzahl}"
    return f"{sprache.wort(n)} {mehrzahl}"


def _sierra(e: dict, schwach_bis: float) -> str:
    satz = _kopf(e)
    satz += (f" Am ersten April {_j(e['letztes_jahr'])} erreichte der Schnee an den Messstationen "
             f"{sprache.prozent(e['letzter_anteil'])} des Normalen.")
    if e.get("mittel_10") is not None:
        satz += f" Im Mittel der letzten zehn Jahre waren es {sprache.prozent(e['mittel_10'])}"
        if e.get("mittel_davor") is not None:
            satz += f", in den Jahren davor {sprache.prozent(e['mittel_davor'])}"
        satz += "."
    satz += (f" Schneearme Jahre unter {sprache.prozent(schwach_bis)}: "
             f"{_geschlecht(e['arme_jahre_10'], 'eines', 'keines')} in den letzten zehn Jahren")
    if e.get("jahre_davor"):
        satz += (f", {_geschlecht(e['arme_jahre_davor'], 'eines', 'keines')} in den "
                 f"{sprache.wort(e['jahre_davor'])} Jahren davor")
    return satz + "."


def _amazonas(e: dict) -> str:
    satz = _kopf(e)
    satz += f" Im Jahr {_j(e['letztes_jahr'])} zählte der Referenzsatellit {_rund(e['letzte_zahl'])} Brandherde"
    if e.get("mittel_vergleich"):
        von, bis = e["vergleich"]
        verh = e["letzte_zahl"] / e["mittel_vergleich"] - 1
        satz += (f", im Mittel der Jahre {_spanne(von, bis)} waren es {_rund(e['mittel_vergleich'])}; "
                 f"das sind {sprache.prozent(abs(verh))} {'mehr' if verh >= 0 else 'weniger'}")
    satz += ". Wechselt der Referenzsatellit, kann die Reihe springen."
    if e.get("status") == "unvollständig":
        satz += " Noch nicht alle Jahre sind geladen."
    return satz


MASSE = {  # Name, Einheit, Nachkommastellen, Zeitraum des letzten Werts
    "jahresregen": ("Regen im Wasserjahr von Oktober bis September", "Millimeter", 0, "im Wasserjahr bis September"),
    "sommer_tmax": ("mittlere Tageshöchsttemperatur von Juni bis August", "Grad", 1, "im Sommer"),
    "jahres_tmittel": ("Jahresmitteltemperatur", "Grad", 1, "im Jahr"),
    "heisse_tage": ("Tage mit mindestens dreißig Grad", "Tage", 0, "im Jahr"),
    "kaeltetage": ("Wintertage von November bis Februar mit einem Tagesmittel bis sieben Grad", "Tage", 0,
                   "im Winter bis Februar"),
}


def _zahl(x: float, stellen: int) -> str:
    return sprache.wort(round(x)) if stellen == 0 else sprache.komma(x, stellen)


def _punkt(p: dict) -> str:
    satz = _kopf(p)
    stuecke = []
    for name, b in (p.get("masse") or {}).items():
        text, einheit, stellen, zeitraum = MASSE.get(name, (name, "", 1, "im Jahr"))
        teil = f"{text}: {_zahl(b['letzter_wert'], stellen)} {einheit} {zeitraum} {_j(b['letztes_jahr'])}"
        if b.get("mittel_10") is not None:
            teil += f", im Mittel der letzten zehn Jahre {_zahl(b['mittel_10'], stellen)}"
        if b.get("mittel_anfang") is not None:
            teil += f", in der Zeit von {_spanne(*b['anfang'])} im Mittel {_zahl(b['mittel_anfang'], stellen)}"
        stuecke.append(teil)
        if b.get("trend_30") is not None:
            t = b["trend_30"]
            stellen_t = max(1, stellen)
            if round(t, stellen_t) == 0:
                stuecke[-1] += ", ohne erkennbaren Trend über dreißig Jahre"
            else:
                stuecke[-1] += (f", Trend {'plus' if t > 0 else 'minus'} {_menge(abs(t), stellen_t)} "
                                f"{einheit} je Jahrzehnt")
    if stuecke:
        satz += " " + ". ".join(s[0].upper() + s[1:] for s in stuecke) + "."
    else:
        satz += " Die Reihen sind noch nicht vollständig geladen."
    return satz


# ------------------------------------------------------------------ Gesamt
def _quartal(q: str) -> str:
    jahr, _, teil = q.partition("-")
    return f"{QUARTALE.get(teil, teil)} Quartal {_j(jahr)}"


def absaetze(bericht: dict, k: dict | None = None) -> list[str]:
    k = k or {}
    ref = k.get("referenz") or {"von": 1951, "bis": 1980}
    ind = bericht["indikatoren"]
    liste = [f"Das Kipppunkt-Register für das {_quartal(bericht['quartal'])}. Es zeigt langsame Messreihen, "
             "an denen sich Grundannahmen über Anbauregionen verschieben können. Es schaltet keine Ampel und "
             "handelt nicht; bewertet wird gemeinsam im Quartal."]
    if not bericht.get("vollstaendig"):
        liste.append("Noch nicht alle Reihen sind gesammelt. Der Bericht wird in den nächsten Tagen ergänzt.")
    namen = {"kaltfleck": "Kaltfleck südlich von Grönland", "amoc": "Umwälzströmung im Atlantik",
             "el_nino": "Häufung starker El Niños", "sierra_schnee": "Schnee in der Sierra Nevada",
             "amazonas_braende": "Brandherde im Amazonasgebiet", "punkte": "Temperatur- und Regenreihen"}
    for schluessel, name in namen.items():
        e = ind.get(schluessel)
        if not e:
            continue
        if e.get("status") == "Fehler":
            liste.append(_fehler(name))
            continue
        if schluessel == "kaltfleck":
            liste.append(_kaltfleck(e, (ref["von"], ref["bis"])))
        elif schluessel == "amoc":
            liste.append(_amoc(e))
        elif schluessel == "el_nino":
            c = k.get("el_nino") or {}
            liste.append(_el_nino(e, c.get("stark_ab", 1.5), c.get("sehr_stark_ab", 2.0)))
        elif schluessel == "sierra_schnee":
            liste.append(_sierra(e, (k.get("sierra_schnee") or {}).get("schwach_bis", 0.5)))
        elif schluessel == "amazonas_braende":
            liste.append(_amazonas(e))
        elif schluessel == "punkte":
            for p in (e.get("punkte") or {}).values():
                liste.append(_punkt(p))
            if e.get("status") == "unvollständig":
                liste.append("Bei den Temperatur- und Regenreihen fehlen noch Jahre; sie werden an den nächsten Tagen nachgeladen.")
    liste.append("Bewertet wird gemeinsam im Quartal. Das ist eine Denkhilfe, keine Anlageberatung.")
    return liste


def zustand(bericht: dict) -> str:
    werte = [e.get("status") for e in bericht["indikatoren"].values()]
    if werte and all(w == "Fehler" for w in werte):
        return "Fehler"
    return "in Ordnung" if bericht.get("vollstaendig") else "Warnung"


def schreibe(bericht: dict, ordner: Path, k: dict | None = None) -> list[Path]:
    zeit = datetime.fromisoformat(bericht["stand"])
    stuecke = vorlesen.aufteilen(absaetze(bericht, k), vorlesen.stempel(zeit))
    pfade = vorlesen.schreibe_teile(ordner, "kipppunkte", stuecke)
    offen = [n for n, e in bericht["indikatoren"].items() if e.get("status") != "ok"]
    status = (f"Agent: Kipppunkt-Register (vierteljährlich, GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {zustand(bericht)}\n"
              f"Quartal: {bericht['quartal']}\n"
              f"Ergebnis: abgabe/kipppunkte-teil-1.md"
              + (f" bis kipppunkte-teil-{len(stuecke)}.md" if len(stuecke) > 1 else "")
              + ", daten/kipppunkte.json\n"
              + (f"Offen: {', '.join(offen)}\n" if offen else "")
              + vorlesen.umfang_zeile(stuecke))
    speicher.schreibe_text(ordner / "status-kipppunkte.md", status)
    return pfade


def zusammenfassung(bericht: dict) -> str:
    zeilen = [f"## Kipppunkt-Register {bericht['quartal']}, {bericht['stand']}", "",
              f"- vollständig: {bericht.get('vollstaendig')}"]
    for n, e in bericht["indikatoren"].items():
        if e.get("status") == "Fehler":
            zeilen.append(f"- {n}: Fehler, {e.get('meldung')}")
            continue
        kurz = {s: e.get(s) for s in ("schere_letzte_5", "trend_30", "letzte_12_monate", "trend_je_jahrzehnt",
                                      "letzter_anteil", "mittel_10", "letzte_zahl", "mittel_vergleich") if e.get(s) is not None}
        if n == "punkte":
            kurz = {kz: {m: (b["letzter_wert"], b.get("trend_30")) for m, b in p["masse"].items()}
                    for kz, p in (e.get("punkte") or {}).items()}
        zeilen.append(f"- {n}: {e.get('status')}, {kurz}")
    return "\n".join(zeilen) + "\n"
