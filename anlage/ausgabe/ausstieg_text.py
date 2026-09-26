"""Vorlesetext des Ausstiegs-Vergleichs. Zahlen ausgeschrieben, keine Tabellen."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen
from .metall_text import _punkte

WOCHENTAGE = vorlesen.WOCHENTAGE
EINHEIT = {"Handelstage": ("Handelstag", "Handelstage"), "Monate": ("Monat", "Monate")}


def _prozent(anteil: float) -> str:
    """0,123 → „plus zwölf Prozent“, −0,05 → „minus fünf Prozent“."""
    p = round(anteil * 100)
    if p == 0:
        return "null Prozent"
    return f"{'plus' if p > 0 else 'minus'} {'ein' if abs(p) == 1 else sprache.wort(abs(p))} Prozent"


def _dauer(x: float, einheit: str) -> str:
    eins, mehr = EINHEIT.get(einheit, (einheit, einheit))
    n = round(x)
    return f"einen {eins}" if n == 1 else f"{sprache.wort(n)} {mehr}"


def _faelle(n: int) -> str:
    return "ein Fall" if n == 1 else f"{sprache.wort(n)} Fälle"


def _name(v: dict) -> str:
    n = sprache.ausschreiben(v.get("kurz") or v["name"])
    return n[0].upper() + n[1:]


def _variante(v: dict, z: dict, vergleich: bool) -> str:
    satz = f"{_name(v)}: {_prozent(v['mittel'])}"
    if vergleich and v.get("vorsprung") is not None:
        satz += f", gegen den Vergleich {_punkte(v['vorsprung'])}"
    satz += (f", {'einer' if v['im_plus'] == 1 else sprache.wort(v['im_plus'])} von {sprache.wort(v['n'])} im Plus"
             f", gehalten {_dauer(v['dauer'], z['einheit'])}")
    if v["schlechtester"] is not None and v["schlechtester"] < 0:
        satz += f", schlechtester Fall {_prozent(v['schlechtester'])}"
    return satz + "."


def _vergleich_absatz(titel: str, z: dict, vergleich: bool) -> str:
    if not z["faelle_gesamt"]:
        return f"{titel}: noch keine auswertbaren Fälle."
    teile = [f"{titel}: {_faelle(z['faelle_gesamt'])}."]
    if z["offen"]:
        teile.append("Einer ist noch nicht abgeschlossen und zählt nicht mit." if z["offen"] == 1
                     else f"{sprache.wort(z['offen']).capitalize()} sind noch nicht abgeschlossen und zählen nicht mit.")
    if not z["verglichen"]:
        return " ".join(teile)
    teile.append("Im Mittel bis zum Ausstieg.")
    for v in z["varianten"]:
        teile.append(_variante(v, z, vergleich))
    namen = {v["kennung"]: v for v in z["varianten"]}
    mass = "beim Vorsprung" if z["massstab"] == "vorsprung" else "beim Ergebnis"
    if z.get("vorn"):
        teile.append(f"Vorn {mass}: {_name(namen[z['vorn']])}.")
    elif len(z.get("vorn_gleichauf") or []) == len(z["varianten"]):
        teile.append("Alle Regeln liegen gleichauf.")
    elif z.get("vorn_gleichauf"):
        teile.append(f"Gleichauf vorn {mass}: {sprache.aufzaehlung([_name(namen[k]) for k in z['vorn_gleichauf']])}.")
    if z.get("gipfel_mittel") is not None:
        teile.append(f"Der beste denkbare Ausstieg hätte im Mittel {_prozent(z['gipfel_mittel'])} gebracht; "
                     "den trifft keine Regel.")
    if z["verglichen"] < 5:
        teile.append("Bei so wenigen Fällen kann ein einzelner Ausreißer die Reihenfolge drehen.")
    return " ".join(teile)


def absaetze(e: dict) -> list[str]:
    heute = date.fromisoformat(e["datum"])
    liste = [f"Ausstiegsregeln im Vergleich, gerechnet am {WOCHENTAGE[heute.weekday()]}, dem {sprache.datum(heute)}. "
             "Das System sagt, wann sich ein Blick lohnt. Hier steht, wann man jeweils wieder ausgestiegen wäre: "
             "wenige, vorher festgelegte Regeln an denselben Fällen wie im Rückblick. Gemessen wird bis zum Ausstieg; "
             "verglichen werden nur Fälle, die unter allen Regeln schon abgeschlossen sind."]
    for z in e["zweige"].values():
        if z["art"] == "metall":
            if z["status"] != "ok":
                liste.append(f"{z['name']}: noch keine Kurse.")
                continue
            liste.append(f"{z['name']}. Einstieg: {z['einstieg']}. Vergleich: {z['vergleich'].split(' (')[0]}. "
                         + (z.get("spaetestens") or ""))
            for a in z["achsen"].values():
                titel = f"{a['name']} mit {sprache.aufzaehlung(a['werte'])}"
                liste.append(_vergleich_absatz(titel, {**a, "einheit": z["einheit"]}, True))
        elif z["status"] != "ok":
            liste.append(f"{z['name']}: folgt, sobald der erste Rückblick gelaufen ist.")
        else:
            einstieg = f"{z['name']}. Einstieg: {z['einstieg']}."
            einstieg += (" Gemessen am Palmölpreis selbst, ohne Vergleichsmaßstab." if z["art"] == "palmoel"
                         else f" Vergleich: {z['vergleich']}.")
            liste.append(einstieg + " " + (z.get("spaetestens") or ""))
            liste.append(_vergleich_absatz(z["name"], z, z["art"] != "palmoel"))
    gilt = e.get("gilt") or {}
    if all(v == "bisher" for v in gilt.values()):
        liste.append("Überall gilt noch die bisherige Regel. Welche gilt, legst du fest; dann baue ich sie ins "
                     "Schattendepot ein. Das ist eine Denkhilfe, keine Anlageberatung.")
    else:
        liste.append("Festgelegt: " + ", ".join(f"{k} {v}" for k, v in gilt.items()) + ". "
                     "Das ist eine Denkhilfe, keine Anlageberatung.")
    return [sprache.ausschreiben(a) for a in liste]


def schreibe(e: dict, ordner: Path) -> list[Path]:
    zeit = datetime.fromisoformat(e["stand"])
    stuecke = vorlesen.aufteilen(absaetze(e), vorlesen.stempel(zeit))
    pfade = vorlesen.schreibe_teile(ordner, "ausstieg", stuecke)
    ergebnis = ("abgabe/ausstieg-teil-1.md" if len(stuecke) == 1
                else f"abgabe/ausstieg-teil-1.md bis ausstieg-teil-{len(stuecke)}.md")
    vorn = []
    for z in e["zweige"].values():
        if z["art"] == "metall":
            vorn += [f"{a['name']} {a.get('vorn') or '/'.join(a.get('vorn_gleichauf') or [])}"
                     for a in z.get("achsen", {}).values()]
        elif z["status"] == "ok":
            vorn.append(f"{z['name']} {z.get('vorn') or '/'.join(z.get('vorn_gleichauf') or [])}")
    status = ("Agent: Ausstiegs-Vergleich (auf GitHub, sonntags mit dem Nachprüfer)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {e['zustand']}\n"
              f"Ergebnis: {ergebnis}, daten/ausstieg.json\n"
              f"Vorn: {', '.join(vorn) or 'noch nichts'}\n"
              + vorlesen.umfang_zeile(stuecke))
    speicher.schreibe_text(ordner / "status-ausstieg.md", status)
    return pfade


def zusammenfassung(e: dict) -> str:
    zeilen = [f"## Ausstieg, {e['stand']}, Zustand {e['zustand']}", ""]

    def block(titel, z):
        zeilen.append(f"- {titel}: {z['faelle_gesamt']} Fälle, verglichen {z['verglichen']}, offen {z['offen']}, "
                      f"vorn {z['vorn']} ({z['massstab']}), Gipfel {z.get('gipfel_mittel')}")
        for v in z["varianten"]:
            zeilen.append(f"  - {v['kennung']}: mittel {v['mittel']}, median {v['median']}, vorsprung {v['vorsprung']}, "
                          f"plus {v['im_plus']}/{v['n']}, schlechtester {v['schlechtester']}, dauer {v['dauer']}, {v['gruende']}")

    for z in e["zweige"].values():
        if z["art"] == "metall":
            for a in z.get("achsen", {}).values():
                block(f"{z['name']} {a['name']}", a)
        elif z["status"] == "ok":
            block(z["name"], z)
        else:
            zeilen.append(f"- {z['name']}: {z['status']}")
    return "\n".join(zeilen) + "\n"
