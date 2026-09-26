"""Vorlesetext des Metall-Agenten (Datenteil). Zahlen ausgeschrieben, keine Tabellen, keine Links."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen

WOCHENTAGE = vorlesen.WOCHENTAGE
KANAL_NAME = {"frist": "Frist", "gegenseite": "US-Maßnahme", "erdbeben": "Erdbeben",
              "starkregen": "Starkregen", "trocken": "Trockenheit"}


def _datum(text: str) -> str:
    return sprache.datum(date.fromisoformat(text[:10]))


def _tage(n: int) -> str:
    return "einem Tag" if n == 1 else f"{sprache.wort(n)} Tagen"


def _punkte(anteil: float) -> str:
    """Vorsprung in Prozentpunkten: 0,12 → „zwölf Prozentpunkte vorn“."""
    p = round(anteil * 100)
    if p == 0:
        return "gleichauf"
    zahl = "ein Prozentpunkt" if abs(p) == 1 else f"{sprache.wort(abs(p))} Prozentpunkte"
    return f"{zahl} {'vorn' if p > 0 else 'zurück'}"


def _veraendert(anteil: float) -> str:
    p = round(anteil * 100)
    if p == 0:
        return "kaum verändert"
    zahl = "ein" if abs(p) == 1 else sprache.wort(abs(p))
    return f"um {zahl} Prozent {'gestiegen' if p > 0 else 'gefallen'}"


def _bekanntmachung(f: dict) -> str:
    return f" (Bekanntmachung Nummer {sprache.wort(f['nummer'])})" if f.get("nummer") else ""


# ------------------------------------------------------------------ Gründe
def _ort(kennung: str, stand: dict) -> str:
    """Nur der Ortsname: „Lincang in Yunnan“ → „Lincang“."""
    return (stand.get("standorte") or {}).get(kennung, kennung).split(" in ")[0]


def _grund(g: dict, stand: dict) -> str:
    """Kurzer Anlass; die Einzelheiten stehen in den Absätzen zu den Kanälen."""
    if g["kanal"] == "frist":
        f = next(x for x in stand["fristen"] if x["kennung"] == g["kennung"])
        nummer = f" Nummer {sprache.wort(f['nummer'])}" if f.get("nummer") else ""
        if g["zustand"] == "abgelaufen":
            return f"Aussetzung{nummer} abgelaufen ohne eingetragene Verlängerung"
        return f"Aussetzung{nummer} endet in {_tage(g['tage'])}"
    if g["kanal"] == "gegenseite":
        return f"US-Maßnahme vom {_datum(g['datum'])}"
    if g["kanal"] == "erdbeben":
        return f"Erdbeben bei {_ort(g['standort'], stand)}"
    if g["kanal"] == "starkregen":
        if g["art"] == "vorhergesagt":
            return f"Starkregen vorhergesagt für {_ort(g['standort'], stand)}"
        return f"Starkregen in {_ort(g['standort'], stand)}"
    if g["kanal"] == "trocken":
        return f"Trockenheit in {_ort(g['standort'], stand)}"
    return g["kanal"]


def _achse(a: dict, stand: dict) -> str:
    kopf = a["name"] + (", der Pilot" if a["pilot"] else "")
    staerkstes = max(a["metalle"], key=lambda m: m["wucht"])
    if a["gruende"]:
        anlaesse = []
        for g in a["gruende"]:
            text = _grund(g, stand)
            if text not in anlaesse:
                anlaesse.append(text)
        satz = f"{kopf}: Gelb. {'Anlass' if len(anlaesse) == 1 else 'Anlässe'}: " + "; ".join(anlaesse[:5])
        if len(anlaesse) > 5:
            satz += f"; dazu {sprache.wort(len(anlaesse) - 5)} weitere"
        satz += "."
        if a["mehrfach"]:
            satz += " Mehrere Kanäle zugleich, das zählt als Bestätigung."
    else:
        satz = f"{kopf}: Grün."
    satz += (f" Wucht {sprache.komma(a['wucht'], 2)}, getragen von "
             f"{staerkstes.get('dativ') or staerkstes['name']}.")
    return satz


# ------------------------------------------------------------------ Kanäle
def _fristen(stand: dict) -> str:
    teile = []
    for f in stand["fristen"]:
        if f["zustand"] == "abgelaufen":
            satz = f"Die {f['name']}{_bekanntmachung(f)} ist seit dem {_datum(f['bis'])} abgelaufen."
        elif f["verlaengert"]:
            satz = (f"Die {f['name']}{_bekanntmachung(f)} ist formell verlängert bis zum "
                    f"{sprache.datum(date.fromisoformat(f['bis']), mit_jahr=True)}, noch {_tage(f['tage'])}.")
        else:
            satz = f"Die {f['name']}{_bekanntmachung(f)} läuft am {_datum(f['bis'])} aus, in {_tage(f['tage'])}."
        if f.get("stand") and not f["verlaengert"]:
            satz += f" Stand: {sprache.ausschreiben(f['stand'])}."
        teile.append(satz)
    if not teile:
        return ""
    return "Fristen. " + " ".join(teile)


def _gegenseite(stand: dict) -> str:
    g = stand["gegenseite"]
    doks = g["dokumente"]
    gewichtig = [d for d in doks if d["gewichtig"]]
    n, m = len(doks), len(gewichtig)
    menge = {0: "steht kein Eintrag", 1: "steht ein Eintrag"}.get(n, f"stehen {sprache.wort(n)} Einträge")
    satz = f"Gegenseite. In den letzten {sprache.wort(g['tage'])} Tagen {menge} zu den Suchbegriffen im US-Bundesregister"
    if n:
        satz += ", davon " + {0: "keiner", 1: "einer"}.get(m, sprache.wort(m)) + " gewichtig"
    satz += "."
    for d in gewichtig[:3]:
        kopf = "Neu seit dem letzten Lauf, vom" if d.get("neu") else "Vom"
        satz += f" {kopf} {_datum(d['datum'])}: {sprache.ausschreiben(d['titel'])}."
    if len(gewichtig) > 3:
        satz += f" Dazu {sprache.wort(len(gewichtig) - 3)} weitere gewichtige Einträge."
    if g.get("herkunft") == "letzter Stand":
        satz += " Das Bundesregister war heute nicht erreichbar; das ist der letzte Stand."
    return satz


def _stoerung(stand: dict) -> str:
    s = stand["stoerung"]
    orte = stand.get("standorte") or {}
    teile = ["Störungen an den Förder- und Hüttenstandorten."]
    if s["erdbeben"]:
        for b in s["erdbeben"][:3]:
            teile.append(f"Erdbeben der Stärke {sprache.komma(b['staerke'], 1)} am {_datum(b['datum'])}, "
                         f"{sprache.wort(b['abstand_km'])} Kilometer von {b['standort_name']}.")
    else:
        teile.append(f"Kein Erdbeben in Reichweite der Standorte in den letzten {sprache.wort(s['gelb_tage'])} Tagen.")
    regen = [e for e in s["starkregen_gemessen"] if e["datum"] >= _grenze(stand)] + s["starkregen_vorhergesagt"]
    if regen:
        for e in regen[:3]:
            art = "vorhergesagt" if e["art"] == "vorhergesagt" else "gemessen"
            teile.append(f"{e['standort_name']}: {sprache.wort(e['mm'])} Millimeter Regen am {_datum(e['datum'])}, {art}.")
    elif s.get("regen_hoechst_mm") is not None:
        teile.append("Kein Starkregen gemessen oder vorhergesagt.")
    for kennung, t in s["trocken"].items():
        ort = orte.get(kennung, kennung)
        if t["urteil"] == "Normal wird geladen":
            teile.append(f"{ort}: Das Regen-Normal wird noch geladen, bisher {sprache.wort(t['jahre'])} "
                         f"von {sprache.wort(t['von'])} Jahren.")
        elif t["urteil"] in ("trocken", "normal"):
            teile.append(f"{ort}: in neunzig Tagen {sprache.prozent(t['anteil'])} des normalen Regens"
                         + (", das gilt als trocken." if t["trocken"] else "."))
        elif t["urteil"] == "Trockenzeit":
            teile.append(f"{ort}: Trockenzeit, das Normale ist zu klein für ein Urteil.")
        else:
            teile.append(f"{ort}: heute kein Urteil zur Trockenheit.")
    return " ".join(teile)


def _grenze(stand: dict) -> str:
    from datetime import timedelta
    return (date.fromisoformat(stand["datum"]) - timedelta(days=stand["stoerung"]["gelb_tage"])).isoformat()


def _preise(stand: dict) -> str:
    teile = [f"Preisprobe gegen {stand['vergleich']['name']}."]
    for p in sorted(stand["preise"].values(), key=lambda p: p["rolle"] != "kandidat"):
        if p["urteil"] == "keine Kurse":
            teile.append(f"{p['name']}: keine Kurse.")
            continue
        satz = f"{p['name']}"
        if p.get("r_kurz") is not None:
            satz += f" ist in fünf Handelstagen {_veraendert(p['r_kurz'])}"
        if p.get("r_lang") is not None:
            satz += f", in zwanzig {_veraendert(p['r_lang'])}"
        if p.get("vorsprung_lang") is not None:
            satz += f", gegen den Vergleich {_punkte(p['vorsprung_lang'])}"
        satz += "."
        if p["urteil"] == "schläft":
            satz += " Der Markt schläft noch."
        elif p["urteil"] == "gelaufen":
            satz += " Der Kurs ist schon gelaufen."
        elif p["urteil"] == "veraltet":
            satz += f" Der letzte Kurs ist vom {_datum(p['letzter'])}, zu alt für ein Urteil."
        teile.append(satz)
    return " ".join(teile)


def _gruppe(name: str, g: dict) -> str | None:
    if not g or not g["n"]:
        return None
    fall = "einem Fall" if g["n"] == 1 else f"{sprache.wort(g['n'])} Fällen"
    satz = f"nach {name} in {fall} im Mittel {_punkte(g['v20'])}"
    if g["treffer"]:
        satz += f", Treffer in {'einem' if g['treffer'] == 1 else sprache.wort(g['treffer'])}"
    return satz


def _rueckblick(stand: dict) -> str:
    teile = ["Ereignis-Rückblick: Vorsprung gegen den Vergleich zwanzig Handelstage nach der Ankündigung."]
    for ticker, r in stand["rueckblick"].items():
        gr = r["gruppen"]
        stuecke = [s for s in (_gruppe("Verschärfungen auf der eigenen Achse", gr["verschaerfung_eigene"]),
                               _gruppe("Lockerungen", gr["lockerung_eigene"]),
                               _gruppe("US-Maßnahmen", gr["gegenseite_eigene"])) if s]
        if not stuecke:
            teile.append(f"{r['name']}: noch keine auswertbaren Fälle.")
            continue
        satz = f"{r['name']}: " + "; ".join(stuecke) + "."
        vor = gr["verschaerfung_eigene"].get("v_vorlauf")
        if vor is not None:
            satz += f" In den zwanzig Tagen davor lag der Wert {_punkte(vor)}."
        satz += {"bestanden": " Nach der vorläufigen Regel bestanden.",
                 "nicht bestanden": " Nach der vorläufigen Regel nicht bestanden.",
                 "zu wenige Fälle": " Zu wenige Fälle für ein Urteil."}[r["urteil"]]
        teile.append(satz)
    return " ".join(teile)


def _quellen(stand: dict) -> str:
    kaputt = [q["name"] for q in stand["quellen"].values() if q["status"] == "Fehler"]
    halb = [q["name"] for q in stand["quellen"].values() if q["status"] == "Warnung"]
    if not kaputt and not halb:
        return "Alle Quellen waren erreichbar."
    satz = ""
    if kaputt:
        satz += "Nicht erreichbar: " + "; ".join(kaputt) + "."
    if halb:
        satz += (" " if satz else "") + "Nur teilweise erreichbar: " + "; ".join(halb) + "."
    return satz


# ------------------------------------------------------------------ Aufbau
def absaetze(stand: dict) -> list[str]:
    heute = date.fromisoformat(stand["datum"])
    liste = [f"Der Metall-Wächter {stand['name']}, Datenteil für {WOCHENTAGE[heute.weekday()]}, "
             f"den {sprache.datum(heute)}. Stufen je Achse aus Fristen, US-Maßnahmen und Störungen an den Standorten. "
             "Rot setzt nur der Wächter in der Cloud, wenn eine Meldung aus Peking dazukommt. "
             "Die Wucht sagt, wie stark China ein Metall beherrscht und wie schwer es zu ersetzen ist, von null bis eins."]
    for w in stand.get("wechsel") or []:
        liste.append(f"Neu seit dem letzten Lauf: Die {stand['achsen'][w['achse']]['name']} ist von "
                     f"{w['vorher']} auf {w['jetzt']} gesprungen.")
    for a in stand["reihenfolge"]:
        liste.append(_achse(stand["achsen"][a], stand))
    for text in (_fristen(stand), _gegenseite(stand), _stoerung(stand), _preise(stand), _rueckblick(stand),
                 _quellen(stand)):
        if text:
            liste.append(text)
    liste.append("Die Stufen sind vorläufig, bis der Rückblick bestanden ist. Das ist eine Denkhilfe, keine Anlageberatung.")
    return [sprache.ausschreiben(a) for a in liste]


def schreibe(stand: dict, ordner: Path) -> list[Path]:
    zeit = datetime.fromisoformat(stand["stand"])
    praefix = f"metall-{stand['land']}"
    stuecke = vorlesen.aufteilen(absaetze(stand), vorlesen.stempel(zeit))
    pfade = vorlesen.schreibe_teile(ordner, praefix, stuecke)
    ergebnis = (f"abgabe/{praefix}-teil-1.md" if len(stuecke) == 1
                else f"abgabe/{praefix}-teil-1.md bis {praefix}-teil-{len(stuecke)}.md")
    stufen = ", ".join(f"{stand['achsen'][a]['name']} {stand['achsen'][a]['stufe']}" for a in stand["reihenfolge"])
    status = (f"Agent: Metall-Wächter {stand['name']} (Datenlauf auf GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {stand['zustand']}\n"
              f"Ergebnis: {ergebnis}, daten/metall/{stand['land']}/stand.json\n"
              f"Stufen: {stufen}\n"
              + vorlesen.umfang_zeile(stuecke))
    speicher.schreibe_text(ordner / f"status-{praefix}.md", status)
    return pfade


def zusammenfassung(stand: dict) -> str:
    zeilen = [f"## Metall {stand['land']}, {stand['stand']}, Zustand {stand['zustand']}", ""]
    for a in stand["reihenfolge"]:
        e = stand["achsen"][a]
        zeilen.append(f"- {a}: {e['stufe']} (Wucht {e['wucht']}), Gründe {[g['kanal'] for g in e['gruende']]}")
    for f in stand["fristen"]:
        zeilen.append(f"- Frist {f['kennung']}: {f['zustand']}, {f['tage']} Tage")
    d = stand["gegenseite"]["dokumente"]
    zeilen.append(f"- Bundesregister: {len(d)} Einträge, {sum(1 for x in d if x['gewichtig'])} gewichtig "
                  f"({stand['gegenseite']['herkunft']})")
    for x in [x for x in d if x["gewichtig"]][:8]:
        zeilen.append(f"  - {x['datum']} {x['art']} {x['achsen']}: {x['titel'][:120]}")
    s = stand["stoerung"]
    zeilen.append(f"- Erdbeben: {s['erdbeben_gesamt']} gesamt, {len(s['erdbeben'])} in Reichweite; "
                  f"Regen höchst {s['regen_hoechst_mm']}; trocken {s['trocken']}")
    for t, p in stand["preise"].items():
        zeilen.append(f"- {t}: {p['urteil']}, r5 {p.get('r_kurz')}, r20 {p.get('r_lang')}, v20 {p.get('vorsprung_lang')}, "
                      f"letzter {p.get('letzter')}")
    for t, r in stand["rueckblick"].items():
        g = r["gruppen"]
        zeilen.append(f"- Rückblick {t}: {r['urteil']}; verschärfung eigene {g['verschaerfung_eigene']}; "
                      f"alle {g['verschaerfung_alle']}; lockerung {g['lockerung_eigene']}; gegenseite {g['gegenseite_eigene']}")
    for kennung, qq in stand["quellen"].items():
        zeilen.append(f"- Quelle {kennung}: {qq['status']} {qq.get('meldung') or ''}")
    return "\n".join(zeilen) + "\n"
