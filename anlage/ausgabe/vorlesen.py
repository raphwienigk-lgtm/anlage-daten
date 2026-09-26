"""Vorlesetext aus stand.json, im gemeinsamen Vorlese-Format.

Zeile 1 „Stand: …“, Zeile 2 „Teil x von y“, höchstens 6500 Zeichen je Teil,
keine Tabellen, keine Links, Zahlen ausgeschrieben.

Das ist die Rohfassung aus den Zahlen. Urteile (Meldungen, Depot, Veto aus Gmail)
ergänzt später der Cloud-Bewerter.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .. import speicher
from . import sprache

GRENZE = 6500
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


# ------------------------------------------------------------------ Bausteine
_FEHLT = {
    "Zeitfenster knapp": ("das Zeitfenster ist noch weit offen", "das Zeitfenster ist unbekannt"),
    "Gegenkräfte überwiegen nicht": ("die Gegenkräfte überwiegen", "die Gegenkräfte sind unbekannt"),
    "Markt schläft noch": ("der Preis ist schon gelaufen", "die Preisprobe fehlt"),
    "Ostende der Kaskade bestätigt": ("das Ostende der Kaskade ist nicht bestätigt",
                                      "die Kaskade ist ohne Daten"),
}
_KREUZ = {
    "nur Osten": "im Westen fehlt die Bestätigung durch zu viel Regen",
    "nur Westen": "im Osten fehlt die Trockenheit",
    "keiner": "keiner der beiden Regenzeugen schlägt an",
    "Westzeuge ohne Urteil": "der Westzeuge in Ostafrika hat noch kein Urteil",
    "Ostzeuge ohne Urteil": "der Ostzeuge auf Sumatra und Borneo hat noch kein Urteil",
}


def _fehlt_text(bedingung: dict) -> str:
    if bedingung["name"].startswith("Kreuzbestätigung"):
        return _KREUZ.get(bedingung.get("stand"), "die Kreuzbestätigung fehlt")
    nein, unbekannt = _FEHLT.get(bedingung["name"], (bedingung["name"] + ": nein",
                                                     bedingung["name"] + ": unbekannt"))
    return unbekannt if bedingung["erfuellt"] is None else nein


def _ampel_absatz(b: dict) -> str:
    name = b["name"]
    ampel = b.get("ampel")
    if not ampel:
        return f"{name}: {b.get('hinweis', 'noch nicht bewertet')}."
    farbe = ampel["farbe"]
    if farbe == "ohne Urteil":
        return (f"{name}: heute ohne Urteil. Grund: {ampel['gruende'][0]}. "
                "Im Logbuch bleibt die letzte Farbe stehen.")
    satz = f"{name} steht auf {farbe}"
    if ampel.get("zahl") is not None and farbe != "Grün":
        satz += f", Zahl {sprache.wort(ampel['zahl'])}, vorläufig"
    satz += "."
    if ampel.get("gesperrt"):
        satz += " Achtung: Das Politik-Veto sperrt den Wert."
    elif ampel.get("farbe_rechnung") and ampel["farbe_rechnung"] != farbe:
        satz += f" Ohne Politik-Veto stünde er auf {ampel['farbe_rechnung']}."
    for v in ampel.get("veto") or []:
        if v.get("grund"):
            satz += f" Veto-Grund: {v['grund']}."
    if farbe == "Grün":
        satz += f" Grund: {ampel['gruende'][0]}."
    elif farbe == "Gelb":
        fehlt = [_fehlt_text(b) for b in ampel.get("rot_bedingungen") or [] if b["erfuellt"] is not True]
        if fehlt:
            satz += " Für Rot fehlt noch: " + "; ".join(fehlt) + "."
    else:
        satz += " Alle Bedingungen für Rot sind erfüllt. Das ist ein Signal zum Nachdenken, kein Kaufauftrag."
    return satz


def _enso_absatz(enso: dict | None, zeitfenster: dict | None) -> str:
    if not enso:
        return "Der El-Niño-Index war heute nicht lesbar."
    a = enso["aktuell"]
    satz = (f"Der El-Niño-Index liegt für {sprache.jahreszeit(a['jahreszeit'], a['jahr'])} "
            f"bei {sprache.komma(a['wert'], 1, vorzeichen=True)}. ")
    if enso["phase"] == "El Niño":
        satz += f"Das ist ein {enso['staerke_text']}er El Niño."
    elif enso["phase"] == "La Niña":
        satz += f"Das ist eine {enso['staerke_text']}e La Niña."
    else:
        satz += "Das ist neutral."
    ep = enso.get("episode")
    if ep:
        h = ep["hoehepunkt"]
        if ep["laeuft"]:
            satz += f" Die Episode läuft seit {sprache.jahreszeit(ep['beginn']['jahreszeit'], ep['beginn']['jahr'])}."
            if ep.get("beginnend"):
                satz += " Nach der Regel der NOAA gilt sie erst ab fünf Jahreszeiten in Folge als voll."
        else:
            satz += " Die letzte Episode ist vorbei, wirkt aber noch nach."
        satz += (f" Höchster Wert bisher {sprache.komma(h['wert'], 1, vorzeichen=True)} "
                 f"für {sprache.jahreszeit(h['jahreszeit'], h['jahr'])}")
        satz += ", der Höhepunkt ist bestätigt." if ep["hoehepunkt_bestaetigt"] else ", der Höhepunkt ist noch nicht bestätigt."
    neu = enso.get("neue_erwaermung")
    if neu:
        satz += (f" Seit {sprache.jahreszeit(neu['beginn']['jahreszeit'], neu['beginn']['jahr'])} liegt der Index "
                 "wieder über plus null Komma fünf; eine neue Episode zählt erst nach fünf Jahreszeiten.")
    if zeitfenster and zeitfenster.get("wert") is not None:
        if zeitfenster["status"].startswith("Höhepunkt"):
            satz += " Die Uhr für das Zeitfenster läuft erst ab dem bestätigten Höhepunkt."
        else:
            t = zeitfenster["t_monate"]
            vergangen = "ist einer" if t == 1 else f"sind {sprache.wort(t)}"
            satz += (f" Seit dem Höhepunkt {vergangen} von {sprache.wort(zeitfenster['T_monate'])} "
                     f"Monaten vergangen, Zeitfenster {sprache.komma(zeitfenster['wert'], 2)}.")
    return satz


def _stufe(an) -> str:
    return "angeschlagen" if an else ("nicht angeschlagen" if an is False else "ohne Urteil")


def _dipol_absatz(d: dict | None) -> str:
    if not d:
        return ""
    teile = ["Die Kaskade im Indischen Ozean."]
    if d["grundlage"] == "Episode":
        teile.append("Gezählt wird, was seit Beginn der El-Niño-Episode angeschlagen hat.")
    s1 = d["stufe1"]
    teile.append(f"Stufe eins, El Niño: {s1['status']}.")
    s2 = d["stufe2"]
    werte = [e for e in (s2.get("episode") or [s2.get("aktuell") or {}]) if e.get("anomalie_ms") is not None]
    if werte:
        w = next((e for e in reversed(werte) if e.get("an")), werte[-1])
        richtung = "stärker" if w["anomalie_ms"] < 0 else "schwächer"
        teile.append(f"Stufe zwei, Ostwinde vor Sumatra im Mai und Juni {sprache.jahr(w['jahr'])}: "
                     f"{sprache.komma(abs(w['anomalie_ms']), 1)} Meter pro Sekunde {richtung} als normal, "
                     f"{_stufe(s2['an'])}.")
    else:
        status = s2.get("status") or (s2.get("aktuell") or {}).get("status", "ohne Daten")
        teile.append(f"Stufe zwei, Ostwinde vor Sumatra: {status}.")
    s3 = d["stufe3"]
    if s3.get("aktuell"):
        a = s3["aktuell"]
        jahr, monat = (int(x) for x in a["monat"].split("-"))
        satz = (f"Stufe drei, Dipol-Index für {sprache.monat(jahr, monat)}: "
                f"{sprache.komma(a['wert'], 1, vorzeichen=True)} Grad")
        hoch = s3.get("hoechster_seit_beginn")
        if hoch and hoch["monat"] != a["monat"]:
            hj, hm = (int(x) for x in hoch["monat"].split("-"))
            satz += (f", höchster Wert seit Beginn der Episode "
                     f"{sprache.komma(hoch['wert'], 1, vorzeichen=True)} Grad im {sprache.monat(hj, hm)}")
        teile.append(satz + f", {_stufe(s3['an'])}.")
    else:
        teile.append(f"Stufe drei, Dipol-Index: {s3.get('status', 'ohne Daten')}.")
    p = d.get("prognose") or {}
    if p.get("status") in ("eingetragen", "veraltet"):
        satz = ("Laut Handeingabe erwartet das australische Wetteramt: "
                f"{p.get('aussage') or p.get('richtung') or 'ohne Angabe'}.")
        if p["status"] == "veraltet":
            satz += f" Diese Eingabe ist {sprache.wort(p['alter_tage'])} Tage alt und sollte erneuert werden."
        teile.append(satz)
    teile.append("Das Ostende gilt als bestätigt." if d["ostende_bestaetigt"]
                 else "Das Ostende ist noch nicht bestätigt.")
    return " ".join(teile)


def _zeugen_absatz(d: dict | None) -> str:
    if not d:
        return ""
    z = d["zeugen"]
    teile = []
    ost = z["ost"]["aktuell"]
    if ost.get("anteil") is not None:
        teile.append(f"Regen auf Sumatra und Borneo in den letzten {sprache.wort(ost['zeitraum_tage'])} Tagen: "
                     f"{sprache.prozent(ost['anteil'])} des Normalen"
                     + (", das gilt als trocken." if ost["an"] else "."))
    else:
        teile.append(f"Regen auf Sumatra und Borneo: {ost.get('status')}.")
    ost_ep = z["ost"].get("episode")
    if ost_ep and ost_ep.get("an"):
        tage = "einem Tag" if ost_ep["trockene_tage"] == 1 else f"{sprache.wort(ost_ep['trockene_tage'])} Tagen"
        teile.append(f"Seit Beginn der Episode lag dieser Neunzig-Tage-Regen an {tage} unter der Trockenschwelle, "
                     f"am tiefsten bei {sprache.prozent(ost_ep['tiefster_anteil'])} des Normalen.")
    west = z["west"]["aktuell"]
    if west.get("status") == "außer Saison":
        teile.append("Ostafrika: Die kurze Regenzeit beginnt im Oktober, bis dahin schweigt der Westzeuge.")
        letzte = west.get("letzte_saison") or {}
        if letzte.get("anteil") is not None and letzte.get("an") is not None:
            teile.append(f"Die letzte Regenzeit brachte {sprache.prozent(letzte['anteil'])} des Normalen.")
    elif west.get("anteil") is not None and west.get("an") is not None:
        teile.append(f"Ostafrika, kurze Regenzeit bisher: {sprache.prozent(west['anteil'])} des Normalen"
                     + (", das gilt als nass." if west["an"] else "."))
    else:
        teile.append(f"Ostafrika: {west.get('status')}.")
    k = d["kreuz"]
    texte = {"bestätigt": "Die Kreuzbestätigung steht: zu trocken im Osten und zu nass im Westen.",
             "nur Osten": "Kreuzbestätigung: nur der Osten schlägt an.",
             "nur Westen": "Kreuzbestätigung: nur der Westen schlägt an.",
             "keiner": "Kreuzbestätigung: keiner der beiden Zeugen schlägt an."}
    teile.append(texte.get(k["urteil"], f"Kreuzbestätigung: {k['urteil']}."))
    return " ".join(teile)


def _preis_absatz(b: dict) -> str:
    teile = []
    probe = b.get("preisprobe") or {}
    if probe.get("letzter"):
        jahr, monat = (int(x) for x in probe["letzter"]["datum"][:7].split("-"))
        einheit = (probe.get("einheit") or "").replace("US-Dollar", "Dollar")
        satz = (f"{b['name']} kostete im {sprache.MONATE[monat - 1]} "
                f"{sprache.wort(round(probe['letzter']['wert']))} {einheit}".rstrip())
        if probe.get("z") is not None:
            satz += (f", Z-Wert {sprache.komma(probe['z'], 1, vorzeichen=True)}: "
                     + ("der Markt schläft noch." if probe["markt_schlaeft"] else "der Preis ist schon gelaufen."))
        else:
            satz += "."
        teile.append(satz)
    gegen = b.get("gegenkraefte") or {}
    stuecke = [f"{e['text']} in drei Monaten {sprache.veraenderung(e['veraenderung_3m'])}"
               for e in (gegen.get("einzeln") or {}).values() if e.get("veraenderung_3m") is not None]
    if stuecke:
        teile.append("Gegenkräfte: " + ", ".join(stuecke) + ".")
    for i in b.get("instrumente") or []:
        if i.get("kurs") is None:
            teile.append(f"{i['name']}: {i.get('status')}.")
            continue
        satz = f"{i['name']}"
        if i.get("veraenderung_3m") is not None:
            satz += f" ist in drei Monaten {sprache.veraenderung(i['veraenderung_3m'])}"
        if i.get("z_200") is not None:
            satz += f", Z-Wert {sprache.komma(i['z_200'], 1, vorzeichen=True)}"
        teile.append(satz + ".")
    return " ".join(teile)


def _inland_satz(i: dict) -> str | None:
    urteil = i.get("urteil")
    if urteil in (None, "keine Daten"):
        return None
    letzter = i.get("letzter") or {}
    satz = i["name"]
    if urteil == "veraltet":
        return f"{satz}: der letzte Wert ist vom {sprache.datum(date.fromisoformat(letzter['datum']))}, zu alt für ein Urteil."
    if urteil == "zu kurz":
        return f"{satz}: noch zu wenige Werte für einen Vergleich."
    if i.get("art") == "monatlich":
        d = date.fromisoformat(letzter["datum"])
        satz += f", Stand {sprache.MONATE[d.month - 1]}: in drei Monaten {sprache.veraenderung(i['veraenderung'])}"
    else:
        satz += f": im Mittel der letzten vier Wochen {sprache.veraenderung(i['veraenderung'])} gegenüber drei Monaten zuvor"
    if i.get("status") == "Fehler":
        satz += "; heute nicht erreichbar, das ist der letzte Stand"
    return satz + "."


def _inland_absatz(b: dict) -> str:
    ip = b.get("inlandspreise") or {}
    if ip.get("veraltet"):
        return f"Die Inlandspreise sind seit dem {sprache.datum(date.fromisoformat(ip['veraltet']))} nicht erneuert worden."
    reihen = list((ip.get("reihen") or {}).values())
    if not reihen:
        return ""
    brauchbar = {i.get("land") for i in reihen
                 if i["rolle"] == "fruehzeichen" and i.get("urteil") in ("ruhig", "Frühzeichen", "starkes Frühzeichen")}
    saetze = []
    for i in reihen:
        if i["rolle"] == "ersatz" and i.get("land") in brauchbar:
            continue
        satz = _inland_satz(i)
        if satz:
            saetze.append(satz)
    if not saetze:
        return ""
    text = "Inlandspreise als Frühzeichen für Eingriffe der Regierung: " + " ".join(saetze)
    zeichen = [i for i in reihen if i["rolle"] in ("fruehzeichen", "ersatz")
               and i.get("urteil") in ("Frühzeichen", "starkes Frühzeichen")]
    if zeichen:
        stark = any(i["urteil"] == "starkes Frühzeichen" for i in zeichen)
        text += (f" Das ist ein {'starkes ' if stark else ''}Frühzeichen: Wird es im Inland teuer, greift die Regierung oft ein,"
                 " etwa mit Exportbeschränkungen, und das belastet die Plantagenwerte. Die Ampel ändert es nicht.")
    return text


def _kalender_absatz(kalender: list[dict]) -> str:
    if not kalender:
        return ""
    stuecke = []
    for e in kalender:
        d = date.fromisoformat(e["datum"])
        stuecke.append(f"{'am' if e['genau'] else 'um den'} {sprache.datum(d)}: {e['name']}")
    return "In den nächsten Tagen: " + "; ".join(stuecke) + "."


def _quellen_absatz(quellen: dict) -> str:
    kaputt = [q["name"] for q in quellen.values() if q["status"] == "Fehler"]
    if not kaputt:
        return "Alle Quellen waren erreichbar."
    return ("Heute nicht erreichbar oder nicht lesbar: " + "; ".join(kaputt)
            + ". Wo es geht, stehen die Werte vom letzten erfolgreichen Abruf.")


def _rueckblick_satz(stand: dict) -> str:
    saetze = []
    for b in stand["rohstoffe"].values():
        r = b.get("rueckblick")
        if not r:
            continue
        satz = f"Rückblick {b['name']}: Lernzeit {'bestanden' if r['lernzeit_bestanden'] else 'nicht bestanden'}"
        if r.get("pruefzeit_bestanden") is not None:
            satz += f", Prüfzeit {'bestanden' if r['pruefzeit_bestanden'] else 'nicht bestanden'}"
        elif r.get("pruefzeit") == "verschlossen":
            satz += ", Prüfzeit noch verschlossen"
        saetze.append(satz + ".")
    if not saetze:
        return "Die Zahl hinter der Farbe ist vorläufig, bis der Rückblick steht."
    return " ".join(saetze)


# ------------------------------------------------------------------ Aufbau
def absaetze(stand: dict) -> list[str]:
    heute = date.fromisoformat(stand["datum"])
    liste = [f"Der Anlage-Beobachter für {WOCHENTAGE[heute.weekday()]}, den {sprache.datum(heute)}. "
             "Zuerst die Ampel, dann das Klima, dann die Preise."]
    for e in stand.get("logbuch_neu") or []:
        name = stand["rohstoffe"].get(e["rohstoff"], {}).get("name", e["rohstoff"])
        if e["anlass"] == "Farbwechsel":
            liste.append(f"Neu seit dem letzten Lauf: {name} ist von {e['vorher']} auf {e['farbe']} gesprungen.")
        elif e["anlass"] == "Veto gesetzt":
            liste.append(f"Neu seit dem letzten Lauf: Für {name} gilt jetzt ein Politik-Veto.")
        elif e["anlass"] == "Veto aufgehoben":
            liste.append(f"Neu seit dem letzten Lauf: Das Politik-Veto für {name} ist aufgehoben.")
        if e.get("schattenkauf"):
            liste.append(f"Im Schattendepot gilt {name} ab heute als gedacht gekauft.")
        if e.get("schattenschluss"):
            liste.append(f"Im Schattendepot ist die gedachte Position in {name} geschlossen.")
    for b in stand["rohstoffe"].values():
        liste.append(_ampel_absatz(b))
    klima = stand.get("klima") or {}
    zf = next((b.get("zeitfenster") for b in stand["rohstoffe"].values() if b.get("zeitfenster")), None)
    liste.append(_enso_absatz(klima.get("enso"), zf))
    for text in (_dipol_absatz(klima.get("dipol")), _zeugen_absatz(klima.get("dipol"))):
        if text:
            liste.append(text)
    for b in stand["rohstoffe"].values():
        for text in (_preis_absatz(b), _inland_absatz(b)):
            if text:
                liste.append(text)
    for text in (_kalender_absatz(stand.get("kalender") or []), _quellen_absatz(stand.get("quellen") or {})):
        if text:
            liste.append(text)
    if stand.get("hinweise"):
        liste.append("Hinweis zur Einrichtung: " + " ".join(stand["hinweise"]))
    liste.append(_rueckblick_satz(stand) + " Das ist eine Denkhilfe, keine Anlageberatung.")
    return liste


def stempel(zeit: datetime) -> str:
    return f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}"


def _zerlege(absatz: str, platz: int) -> list[str]:
    """Ein zu langer Absatz wird an Satzenden geteilt."""
    if len(absatz) <= platz:
        return [absatz]
    stuecke, aktuell = [], ""
    for satz in absatz.replace(". ", ".\x00").split("\x00"):
        kandidat = f"{aktuell} {satz}" if aktuell else satz
        if aktuell and len(kandidat) > platz:
            stuecke.append(aktuell)
            aktuell = satz
        else:
            aktuell = kandidat
    if aktuell:
        stuecke.append(aktuell)
    return stuecke


def aufteilen(absaetze_liste: list[str], kopf: str, grenze: int = GRENZE) -> list[str]:
    """Teilt Absätze auf Teile von höchstens `grenze` Zeichen, Kopfzeilen eingerechnet.
    Zeile 1 ist `kopf` („Stand: …“), Zeile 2 „Teil x von y“."""
    kopf_platz = len(kopf) + len("\nTeil 99 von 99\n\n") + 1
    koerper, aktuell = [], ""
    for absatz in (s for a in absaetze_liste for s in _zerlege(a, grenze - kopf_platz)):
        kandidat = f"{aktuell}\n\n{absatz}" if aktuell else absatz
        if aktuell and len(kandidat) + kopf_platz > grenze:
            koerper.append(aktuell)
            aktuell = absatz
        else:
            aktuell = kandidat
    if aktuell:
        koerper.append(aktuell)
    n = len(koerper)
    return [f"{kopf}\nTeil {i} von {n}\n\n{text}\n" for i, text in enumerate(koerper, start=1)]


def teile(stand: dict, grenze: int = GRENZE) -> list[str]:
    return aufteilen(absaetze(stand), stempel(datetime.fromisoformat(stand["stand"])), grenze)


def schreibe_teile(ordner: Path, praefix: str, stuecke: list[str]) -> list[Path]:
    """Schreibt <praefix>-teil-1.md usw.; alte Teile mit demselben Präfix werden vorher entfernt."""
    ordner.mkdir(parents=True, exist_ok=True)
    for alt in ordner.glob(f"{praefix}-teil-*.md"):
        alt.unlink()
    pfade = []
    for i, text in enumerate(stuecke, start=1):
        pfad = ordner / f"{praefix}-teil-{i}.md"
        speicher.schreibe_text(pfad, text)
        pfade.append(pfad)
    return pfade


def umfang_zeile(stuecke: list[str]) -> str:
    """„Umfang: 1 Teil, etwa 1 Minute Vorlesezeit“ für die Statusdateien."""
    minuten = vorlesezeit_minuten(stuecke)
    return (f"Umfang: {len(stuecke)} Teil{'e' if len(stuecke) > 1 else ''}, "
            f"etwa {minuten} Minute{'n' if minuten != 1 else ''} Vorlesezeit\n")


def vorlesezeit_minuten(stuecke: list[str]) -> int:
    return max(1, round(sum(len(t) for t in stuecke) / 900))


def schreibe(stand: dict, ordner: Path) -> list[Path]:
    """Schreibt anlage-teil-1.md usw. und status-anlage.md. Alte Teile werden vorher entfernt."""
    stuecke = teile(stand)
    pfade = schreibe_teile(ordner, "anlage", stuecke)
    zeit = datetime.fromisoformat(stand["stand"])
    ergebnis = ("abgabe/anlage-teil-1.md" if len(stuecke) == 1
                else f"abgabe/anlage-teil-1.md bis anlage-teil-{len(stuecke)}.md")
    status = (f"Agent: Anlage-Beobachter (Datenlauf auf GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {stand['zustand']}\n"
              f"Ergebnis: {ergebnis}, daten/stand.json\n"
              + umfang_zeile(stuecke))
    speicher.schreibe_text(ordner / "status-anlage.md", status)
    return pfade
