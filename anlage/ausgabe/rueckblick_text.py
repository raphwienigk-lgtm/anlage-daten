"""Vorlesetext des Rückblicks, im gemeinsamen Vorlese-Format.

Zeile 1 „Stand: …“, Zeile 2 „Teil x von y“, höchstens 6500 Zeichen je Teil, Zahlen
ausgeschrieben. Dazu eine Statuszeile für Morgenbriefing und Bewerter.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen

BEDINGUNG = {
    "Zeitfenster knapp": "das Zeitfenster war noch weit offen",
    "Gegenkräfte überwiegen nicht": "die Gegenkräfte überwogen",
    "Markt schläft noch": "der Preis war schon gelaufen",
    "Ostende der Kaskade bestätigt": "das Ostende der Kaskade war nicht bestätigt",
    "Kreuzbestätigung West und Ost": "die Kreuzbestätigung fehlte",
}
OHNE_DATEN = " (ohne Daten)"
ERNTE_DELLE = 0.03       # Ernte wird nur genannt, wenn ihr Wachstum mindestens drei Punkte unter dem Mittel liegt


def _bedingung(name: str) -> str:
    if name.endswith(OHNE_DATEN):
        grund = name[: -len(OHNE_DATEN)]
        return f"für „{grund}“ fehlten Daten"
    return BEDINGUNG.get(name, f"„{name}“ war nicht erfüllt")


def _monat(text: str) -> str:
    return sprache.monat(int(text[:4]), int(text[5:7]))


def _pm(anteil: float | None) -> str:
    """Veränderung mit Vorzeichen: plus zwölf Prozent, minus fünf Prozent."""
    if anteil is None:
        return "unbekannt"
    p = round(anteil * 100)
    if p == 0:
        return "null Prozent"
    return f"{'plus' if p > 0 else 'minus'} {sprache.wort(abs(p))} Prozent"


def _punkte(anteil: float | None) -> str:
    if anteil is None:
        return "unbekannt"
    p = round(anteil * 100)
    if p == 0:
        return "null Prozentpunkte"
    einheit = "Prozentpunkt" if abs(p) == 1 else "Prozentpunkte"
    return f"{'plus' if p > 0 else 'minus'} {sprache.wort(abs(p))} {einheit}"


def _stueck(n: int, einzahl: str, mehrzahl: str, artikel: str = "ein") -> str:
    if n == 0:
        return f"keine {mehrzahl}"
    if n == 1:
        return f"{artikel} {einzahl}"
    return f"{sprache.wort(n)} {mehrzahl}"


def _prozent_rund(anteil: float) -> str:
    return sprache.wort(round(anteil * 100))


# ------------------------------------------------------------------ Bausteine
def _grund(g: dict) -> str:
    art = g["art"]
    if art == "zu_wenige":
        if g["ist"] == 0:
            gab = "es gab kein bewertbares Signal"
        else:
            gab = f"es gab nur {_stueck(g['ist'], 'bewertbares Signal', 'bewertbare Signale')}"
        return f"{gab}, verlangt sind mindestens {sprache.wort(g['soll'])}"
    if art == "mehrwert":
        if g["ist"] is None:
            return "der Mehrwert ist nicht berechenbar"
        return f"der Mehrwert liegt bei {_punkte(g['ist'])}, verlangt sind mindestens {_punkte(g['soll'])}"
    if art == "fehlalarme":
        return (f"es gab {_stueck(g['ist'], 'Fehlalarm', 'Fehlalarme')} und nur "
                f"{_stueck(g['soll'], 'Treffer', 'Treffer')}")
    if art == "zufall":
        if g["ist"] is None:
            return "die Zufallsprobe ist nicht berechenbar"
        return (f"{_prozent_rund(g['ist'])} von hundert zufälligen Ziehungen waren genauso gut, "
                f"erlaubt sind höchstens {_prozent_rund(g['soll'])}")
    return art


def _urteil_satz(b: dict, was: str) -> str:
    u = b["urteil"]
    if u["bestanden"]:
        return f"Ergebnis {was}: bestanden."
    return f"Ergebnis {was}: nicht bestanden. " + " ".join(f"Grund: {_grund(g)}." for g in u["gruende"])


def _zahlen_satz(b: dict) -> str:
    mal = "einmal" if b["anzahl"] == 1 else f"{sprache.wort(b['anzahl'])} Mal"
    teile = [f"Die Ampel sprang {mal} neu auf Rot und eröffnete dabei jeweils eine gedachte Position."
             if b["anzahl"] else "Die Ampel sprang in diesem Zeitraum nie auf Rot."]
    if b["anzahl"]:
        teile.append(f"Davon {_stueck(b['treffer'], 'Treffer', 'Treffer')} und "
                     f"{_stueck(b['fehlalarme'], 'Fehlalarm', 'Fehlalarme')}."
                     + (f" Noch offen: {sprache.wort(b['offen'])}." if b["offen"] else ""))
    if b["mittel_12"] is not None:
        teile.append(f"Zwölf Monate nach Rot lag der Preis im Mittel bei {_pm(b['mittel_12'])}, "
                     f"über alle Monate bei {_pm(b['basis_12'])}. Der Mehrwert beträgt {_punkte(b['mehrwert'])}.")
    if b["zufall_anteil"] is not None:
        teile.append(f"Zufallsprobe: {_prozent_rund(b['zufall_anteil'])} von hundert Ziehungen gleich vieler "
                     "zufälliger Monate waren mindestens so gut.")
    if b.get("basis_trefferquote") is not None:
        teile.append(f"Zum Vergleich: In {_prozent_rund(b['basis_trefferquote'])} von hundert Monaten stieg der Preis "
                     "binnen eines Jahres ohnehin irgendwann um die Treffergrenze; so oft trifft man auch ohne Ampel.")
    return " ".join(teile)


def _signal_satz(s: dict) -> str:
    satz = f"Rot im {_monat(s['monat'])}"
    if s.get("zahl") is not None:
        satz += f", Zahl {sprache.wort(s['zahl'])}"
    if s["urteil"] == "offen":
        satz += ": noch offen"
        if s.get("nach_3") is not None:
            satz += f", nach drei Monaten {_pm(s['nach_3'])}"
        return satz + "."
    satz += (f": nach zwölf Monaten {_pm(s['nach_12'])}, höchster Stand {_pm(s['hoechster'])} "
             f"nach {_stueck(s['gipfel_nach_monaten'], 'Monat', 'Monaten', 'einem')}, "
             f"tiefster Stand {_pm(s['tiefster'])}; {s['urteil']}.")
    if s.get("schluss"):
        satz += f" Grün im {_monat(s['schluss'])} schloss die Position bei {_pm(s.get('bei_schluss'))}."
    return satz


EINORDNUNG = {"rechtzeitig": "rechtzeitig mit Rot", "spät": "zu spät erkannt",
              "nur Gelb": "nur mit Gelb", "verpasst": "verpasst"}


def _bewegungen_absaetze(b: dict, treffer: float, bewegung: float) -> list[str]:
    z = b["bewegungen_zaehlung"]
    if not z["gesamt"]:
        return [f"Große Preisbewegungen von mindestens {_prozent_rund(bewegung)} Prozent gab es in diesem Zeitraum keine."]
    e = z["el_nino"]
    kopf = (f"Große Preisbewegungen, also Anstiege um mindestens {_prozent_rund(bewegung)} Prozent binnen eines Jahres: "
            f"{sprache.wort(z['gesamt'])}. Davon im Zeitfenster eines El Niño, also von drei Monaten vor seinem "
            f"Höhepunkt bis zum Ende des Zeitfensters: {sprache.wort(z['mit_el_nino'])}.")
    if z["mit_el_nino"]:
        kopf += (f" Von diesen erkannte die Ampel rechtzeitig mit Rot: {sprache.wort(e['rechtzeitig'])}; "
                 f"zu spät: {sprache.wort(e['spät'])}; nur mit Gelb: {sprache.wort(e['nur Gelb'])}; "
                 f"gar nicht: {sprache.wort(e['verpasst'])}.")
    absaetze_liste = [kopf]
    liste = []
    for g in (g for g in b["bewegungen"] if g["el_nino"]):
        satz = f"Ab {_monat(g['beginn'])} {_pm(g['anstieg'])} bis {_monat(g['gipfel'])}, {EINORDNUNG[g['einordnung']]}"
        if g.get("rot_seit"):
            satz += f", Rot seit {_monat(g['rot_seit'])}"
        liste.append(satz + ".")
    if liste:
        absaetze_liste.append("Die Anstiege im Zeitfenster eines El Niño: " + " ".join(liste))
    ohne = sorted({int(g["beginn"][:4]) for g in b["bewegungen"] if not g["el_nino"]})
    if ohne:
        absaetze_liste.append("Ohne El Niño begannen große Anstiege in den Jahren "
                              + ", ".join(sprache.jahr(j) for j in ohne)
                              + ". Die soll die Ampel nicht fangen; sie zeigen, was andere Treiber bewegt haben.")
    return absaetze_liste


def _engpass_satz(b: dict) -> str:
    eng = b.get("engpaesse") or {}
    if not eng:
        return ""
    teile = [f"{_bedingung(n)} in {_stueck(z, 'Monat', 'Monaten', 'einem')}" for n, z in list(eng.items())[:4]]
    return "Woran Rot am häufigsten scheiterte, gezählt in den Gelb-Monaten: " + "; ".join(teile) + "."


def _episoden_absatz(episoden: list[dict]) -> str:
    if not episoden:
        return "Im Zeitraum lag kein Höhepunkt einer El-Niño-Episode."
    teile = [f"Der Zeitraum enthält {_stueck(len(episoden), 'El-Niño-Episode', 'El-Niño-Episoden', 'eine')}."]
    for ep in episoden:
        h = ep["hoehepunkt"]
        satz = (f"Höhepunkt {sprache.jahreszeit(h['jahreszeit'], h['jahr'])} mit "
                f"{sprache.komma(h['wert'], 1, vorzeichen=True)}: ")
        if ep["hoechste_farbe"]:
            satz += f"höchste Farbe {ep['hoechste_farbe']}, erstmals im {_monat(ep['erster_monat'])}"
        else:
            satz += "ohne Farbe"
        if ep.get("preis_nach_hoehepunkt"):
            p = ep["preis_nach_hoehepunkt"]
            if round(p["wert"] * 100) > 0:
                satz += f"; Preis danach höchstens {_pm(p['wert'])}, im {_monat(p['monat'])}"
            else:
                satz += "; der Preis stieg danach nicht"
        if ep["hoechste_farbe"] == "Gelb" and ep.get("engpass"):
            satz += f"; für Rot fehlte vor allem: {_bedingung(ep['engpass'])}"
        er = ep.get("ernte")
        if er and er["delle"] <= -ERNTE_DELLE:
            satz += (f"; die Ernte in Indonesien und Malaysia wuchs im Wirtschaftsjahr {sprache.jahr(er['jahr'])} "
                     f"nur um {_pm(er['wachstum'])}, sonst im Mittel um {_pm(er['vorher_mittel'])}")
        teile.append(satz + ".")
    return " ".join(teile)


def _kurzbilanz(b: dict) -> str:
    satz = (f"{_stueck(b['anzahl'], 'Signal', 'Signale')}, {_stueck(b['treffer'], 'Treffer', 'Treffer')}, "
            f"{_stueck(b['fehlalarme'], 'Fehlalarm', 'Fehlalarme')}")
    if b.get("mehrwert") is not None:
        satz += f", Mehrwert {_punkte(b['mehrwert'])}"
    if b["urteil"]["bestanden"]:
        return satz + ", bestanden"
    return satz + ", nicht bestanden; Grund: " + "; ".join(_grund(g) for g in b["urteil"]["gruende"])


def _zeitalter_absatz(zeitalter: list[dict]) -> str:
    if not zeitalter:
        return ""
    a, b = zeitalter
    jahr_a = int(a["name"].split()[-1])
    return (f"Getrennt nach Wetterdaten: Bis {sprache.jahr(jahr_a)}, als die Wetterdaten in den Tropen noch "
            f"unsicherer sind, {_kurzbilanz(a['bilanz'])}. Ab {sprache.jahr(jahr_a + 1)} {_kurzbilanz(b['bilanz'])}.")


def _varianten_absatz(varianten: list[dict], T: int) -> str:
    if not varianten:
        return ""
    teile = [f"Zum Vergleich, nicht zum Aussuchen. Mit {sprache.wort(T)} Monaten Zeitfenster wie eingestellt: siehe oben."]
    for v in varianten:
        teile.append(f"Mit {sprache.wort(v['vorlauf_T_monate'])} Monaten: {_kurzbilanz(v['bilanz'])}.")
    teile.append("Liegen die Ergebnisse nah beieinander, ist die Regel robust. Trägt nur eine Einstellung, ist das eher Glück.")
    return " ".join(teile)


def _pruefzeit_absaetze(p: dict, lern_bis: str) -> list[str]:
    ab = int(lern_bis[:4]) + 1
    if p["status"] in ("verschlossen", "noch leer"):
        satz = (f"Die Prüfzeit ab {sprache.jahr(ab)} ist noch verschlossen. Sie wird erst geöffnet, wenn die "
                "Regeln feststehen; das erste Öffnen ist das maßgebliche.")
        if p.get("oeffnungen"):
            erst = p["oeffnungen"][0]
            am = sprache.datum(datetime.fromisoformat(erst["am"]).date(), mit_jahr=True)
            if erst.get("status", "").startswith("Lernzeit"):
                satz = (f"Die Lernzeit wurde am {am} in die frühere Prüfzeit verlängert. Eine unabhängige "
                        "Prüfzeit gibt es damit nicht mehr.")
            else:
                satz = (f"Die Prüfzeit wurde am {am} zum ersten Mal geöffnet. "
                        f"Damals: {_kurzbilanz(erst['ergebnis'])}.")
        return [satz]
    b = p["bilanz"]
    kopf = f"Prüfzeit ab {sprache.jahr(ab)}, {p['status']}."
    if not p.get("unabhaengig", True):
        kopf += (" Achtung: Die Regeln wurden nach dem ersten Öffnen geändert. Dieses Ergebnis ist nicht mehr "
                 "unabhängig; maßgeblich bleibt das erste.")
    liste = [kopf, _urteil_satz(b, "der Prüfzeit"), _zahlen_satz(b)]
    if b["signale"]:
        liste.append(" ".join(_signal_satz(s) for s in b["signale"]))
    return liste


def _grenzen_absatz(e: dict) -> str:
    teile = ["Grenzen des Rückblicks: Politik, Veto und die Vorhersage des australischen Wetteramts fehlen.",
             "Der El-Niño-Index ist der heutige, nachträglich überarbeitete Stand, nicht der damals veröffentlichte.",
             "Die Ostwinde gehen erst ab Juli als ganzes Jahr ein.",
             "Das Normal für Regen und Wind stammt aus den Jahren neunzehnhunderteinundneunzig bis "
             "zweitausendzwanzig, also teils aus der Zukunft des jeweiligen Monats.",
             "Preise und Gegenkräfte sind Monatsdurchschnitte statt Tageskurse; gekauft wird im Gedanken zum "
             "Durchschnitt des Signalmonats."]
    unsicher = e["einstellungen"].get("wetter_unsicher_bis")
    if unsicher:
        teile.append(f"Wetterdaten bis {sprache.jahr(unsicher)} sind in den Tropen unsicherer.")
    hinweise = e["daten"].get("hinweise") or []
    if hinweise:
        teile.append(f"Zu den Daten gibt es {_stueck(len(hinweise), 'Hinweis', 'Hinweise')}; "
                     "sie stehen in der Datei des Rückblicks.")
    return " ".join(teile)


# ------------------------------------------------------------------ Aufbau
def absaetze(e: dict) -> list[str]:
    ein = e["einstellungen"]
    lern = e["lernzeit"]
    b = lern["bilanz"]
    liste = [
        (f"Rückblick {e['name']}. Die Zeitmaschine hat die Ampel für jeden Monat von {_monat(ein['von'])} "
         f"bis {_monat(ein['lernzeit_bis'])} neu berechnet, jeweils zum fünfzehnten und nur mit den Daten, "
         "die damals schon veröffentlicht waren. Gekauft wird im Gedanken bei Rot, geschlossen erst bei Grün, "
         f"wie im Schattendepot. Ein Treffer heißt: Der Preis stieg in den zwölf Monaten danach um mindestens "
         f"{_prozent_rund(ein['treffer_ab'])} Prozent."),
        _urteil_satz(b, "der Lernzeit"),
        (f"Verteilung: {_stueck(b['farben']['Grün'], 'Monat', 'Monate')} Grün, "
         f"{_stueck(b['farben']['Gelb'], 'Monat', 'Monate')} Gelb, {_stueck(b['farben']['Rot'], 'Monat', 'Monate')} Rot"
         + (f", {_stueck(b['farben']['ohne Urteil'], 'Monat', 'Monate')} ohne Urteil." if b["farben"]["ohne Urteil"] else ".")),
        _zahlen_satz(b),
    ]
    if b["signale"]:
        liste.append(" ".join(_signal_satz(s) for s in b["signale"]))
    liste += _bewegungen_absaetze(b, ein["treffer_ab"], ein["bewegung_ab"])
    for text in (_engpass_satz(b), _episoden_absatz(lern.get("episoden") or []),
                 _zeitalter_absatz(lern.get("zeitalter") or []),
                 _varianten_absatz(e.get("varianten") or [], ein["vorlauf_T_monate"])):
        if text:
            liste.append(text)
    liste += _pruefzeit_absaetze(e["pruefzeit"], ein["lernzeit_bis"])
    liste.append(_grenzen_absatz(e))
    liste.append("Das ist eine Denkhilfe, keine Anlageberatung.")
    return liste


def teile(e: dict) -> list[str]:
    return vorlesen.aufteilen(absaetze(e), vorlesen.stempel(datetime.fromisoformat(e["stand"])))


def schreibe(e: dict, ordner: Path) -> list[Path]:
    """Schreibt rueckblick-<kennung>-teil-N.md und status-rueckblick-<kennung>.md."""
    praefix = f"rueckblick-{e['rohstoff']}"
    stuecke = teile(e)
    pfade = vorlesen.schreibe_teile(ordner, praefix, stuecke)
    zeit = datetime.fromisoformat(e["stand"])
    b = e["lernzeit"]["bilanz"]
    p = e["pruefzeit"]
    status = (f"Agent: Rückblick {e['name']} (Zeitmaschine auf GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: Lernzeit {'bestanden' if b['urteil']['bestanden'] else 'nicht bestanden'}, "
              f"Prüfzeit {p['status']}\n"
              f"Ergebnis: abgabe/{praefix}-teil-1.md"
              + (f" bis {praefix}-teil-{len(stuecke)}.md" if len(stuecke) > 1 else "")
              + f", daten/rueckblick/{e['rohstoff']}.json\n"
              f"Umfang: {len(stuecke)} Teil{'e' if len(stuecke) > 1 else ''}, "
              f"etwa {vorlesen.vorlesezeit_minuten(stuecke)} Minuten Vorlesezeit\n")
    speicher.schreibe_text(ordner / f"status-{praefix}.md", status)
    return pfade


def zusammenfassung(e: dict) -> str:
    """Kurzfassung für die Zusammenfassung des GitHub-Laufs (mit Ziffern, nicht zum Vorlesen)."""
    b = e["lernzeit"]["bilanz"]
    zeilen = [f"## Rückblick {e['name']}, {e['stand']}", "",
              f"Lernzeit {e['einstellungen']['von']} bis {e['einstellungen']['lernzeit_bis']}: "
              f"**{'bestanden' if b['urteil']['bestanden'] else 'nicht bestanden'}**", "",
              f"- Signale {b['anzahl']}, Treffer {b['treffer']}, Fehlalarme {b['fehlalarme']}, offen {b['offen']}",
              f"- 12 Monate nach Rot {b['mittel_12']}, alle Monate {b['basis_12']}, Mehrwert {b['mehrwert']}, "
              f"Zufall {b['zufall_anteil']}",
              f"- Rot in: {', '.join(s['monat'] for s in b['signale']) or '–'}",
              f"- Große Bewegungen: {b['bewegungen_zaehlung']}"]
    for v in e.get("varianten") or []:
        vb = v["bilanz"]
        zeilen.append(f"- Variante {v['name']}: Signale {vb['anzahl']}, Treffer {vb['treffer']}, "
                      f"Mehrwert {vb['mehrwert']}, {'bestanden' if vb['urteil']['bestanden'] else 'nicht bestanden'}")
    zeilen.append(f"- Prüfzeit: {e['pruefzeit']['status']}")
    for h in e["daten"].get("hinweise") or []:
        zeilen.append(f"- Hinweis: {h}")
    return "\n".join(zeilen) + "\n"
