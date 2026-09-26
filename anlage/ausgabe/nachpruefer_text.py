"""Vorlesetext des Nachprüfers, im gemeinsamen Vorlese-Format."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .. import speicher
from . import sprache, vorlesen
from .rueckblick_text import _pm, _stueck


def _anzahl(n: int, art: str) -> str:
    """„keine offene Position“, „eine geschlossene Position“, „zwei offene Positionen“."""
    if n == 0:
        return f"keine {art}e Position"
    if n == 1:
        return f"eine {art}e Position"
    return f"{sprache.wort(n)} {art}e Positionen"


def _datum(text: str) -> str:
    return sprache.datum(date.fromisoformat(text[:10]))


def _lauf_absatz(lk: dict) -> str:
    teile = []
    if lk.get("tage_mit_lauf") is None:
        teile.append("Wie oft der tägliche Lauf diese Woche gelang, ist heute nicht bekannt.")
    elif lk["tage_mit_lauf"] == 7:
        teile.append("Der tägliche Lauf gelang an allen sieben Tagen.")
    else:
        fehlend = ", ".join(_datum(t) for t in lk["fehlende_tage"])
        teile.append(f"Der tägliche Lauf gelang an {sprache.wort(lk['tage_mit_lauf'])} von sieben Tagen; "
                     f"es fehlte am {fehlend}.")
    if lk.get("zustand"):
        teile.append(f"Zustand beim letzten Lauf: {lk['zustand']}.")
    if lk.get("hinweise"):
        teile.append(f"Dazu {_stueck(len(lk['hinweise']), 'Hinweis', 'Hinweise')} im Stand.")
    return " ".join(teile)


def _ampel_absatz(name: str, a: dict) -> str:
    if not a.get("farbe"):
        return f"{name}: noch kein Eintrag im Logbuch."
    satz = f"{name} steht seit dem {_datum(a['seit'])} auf {a['farbe']}"
    if a.get("zahl") is not None and a["farbe"] != "Grün":
        satz += f", Zahl {sprache.wort(a['zahl'])}"
    if a.get("gesperrt"):
        satz += ", gesperrt durch ein Veto"
    satz += "."
    wechsel = [w for w in a.get("wechsel") or [] if w.get("anlass") != "Start"]
    if not wechsel:
        satz += " In dieser Woche gab es keinen Wechsel."
    else:
        stuecke = []
        for w in wechsel:
            if w["anlass"] == "Farbwechsel":
                stuecke.append(f"am {_datum(w['tag'])} von {w['vorher']} auf {w['farbe']}")
            else:
                stuecke.append(f"am {_datum(w['tag'])} {w['anlass']}")
        satz += " Wechsel in dieser Woche: " + "; ".join(stuecke) + "."
    return satz


def _position_satz(p: dict) -> str:
    art = "offen" if p["offen"] else f"geschlossen am {_datum(p['bis'])}"
    satz = f"Gedachte Position seit dem {_datum(p['seit'])}, {art}, nach {_stueck(p['tage'], 'Tag', 'Tagen', 'einem')}"
    if p.get("zahl") is not None:
        satz += f", Zahl beim Einstieg {sprache.wort(p['zahl'])}"
    satz += "."
    stuecke = []
    for i in p["instrumente"]:
        if i.get("status") != "ok":
            continue
        stuecke.append(f"{i.get('name', i['ticker'])} {_pm(i['veraenderung'])}, zwischendurch höchstens "
                       f"{_pm(i['hoechster'])} und tiefstens {_pm(i['tiefster'])}")
    if stuecke:
        satz += " Aktien: " + "; ".join(stuecke) + "."
    if p.get("rohstoff"):
        satz += f" Der Rohstoffpreis seitdem: {_pm(p['rohstoff']['veraenderung'])}."
    return satz


def _signal_absatz(name: str, r: dict) -> str:
    sg = r["signale"]
    if not sg["anzahl"]:
        satz = f"{name}: bisher kein echtes Rot-Signal."
    else:
        satz = (f"{name}: bisher {_stueck(sg['anzahl'], 'echtes Signal', 'echte Signale')}, davon "
                f"{_stueck(sg['treffer'], 'Treffer', 'Treffer')} und {_stueck(sg['fehlalarme'], 'Fehlalarm', 'Fehlalarme')}.")
        if sg["offen"]:
            offen = _stueck(sg['offen'], 'Signal ist', 'Signale sind')
            satz += (f" {offen[0].upper() + offen[1:]} noch offen, "
                     "weil die zwölf Monate nicht vorbei sind.")
    rb = r.get("rueckblick")
    if rb:
        satz += (f" Zum Vergleich der Rückblick über die Lernzeit: {_stueck(rb['anzahl'], 'Signal', 'Signale')}, "
                 f"{_stueck(rb['treffer'], 'Treffer', 'Treffer')}, zwölf Monate nach Rot im Mittel {_pm(rb['mittel_12'])}"
                 f" gegenüber {_pm(rb['basis_12'])} über alle Monate; "
                 + ("bestanden." if rb["bestanden"] else "nicht bestanden."))
    else:
        satz += " Ein Rückblick liegt noch nicht vor."
    if r["vorschlag_faellig"]:
        satz += (" Es liegen genug abgeschlossene Signale vor, um die Regeln gemeinsam zu überprüfen. "
                 "Der Nachprüfer schlägt vor, den Rückblick mit den aktuellen Signalen zu vergleichen; verstellt wird nichts selbst.")
    else:
        satz += (f" Für Vorschläge zu den Schwellen braucht es mindestens "
                 f"{sprache.wort(r['mindest_signale'])} abgeschlossene Signale.")
    return satz


def absaetze(e: dict) -> list[str]:
    w = e["woche"]
    liste = [f"Der Nachprüfer für die Woche vom {_datum(w['von'])} bis {_datum(w['bis'])}.",
             _lauf_absatz(e["laufkontrolle"])]
    for r in e["rohstoffe"].values():
        liste.append(_ampel_absatz(r["name"], r["ampel"]))
        offene = [p for p in r["positionen"] if p["offen"]]
        geschlossene = [p for p in r["positionen"] if not p["offen"]]
        if not r["positionen"]:
            liste.append("Im Schattendepot gab es bisher keine gedachte Position.")
        else:
            liste.append(f"Schattendepot {r['name']}: {_anzahl(len(offene), 'offen')}, {_anzahl(len(geschlossene), 'geschlossen')}.")
            for p in offene + geschlossene[-3:]:
                liste.append(_position_satz(p))
        liste.append(_signal_absatz(r["name"], r))
    liste.append("Politik-Vetos aus den Mails sind hier nicht eingerechnet; sie stehen im Bericht des Nachprüfers im Projekt.")
    liste.append("Das ist eine Denkhilfe, keine Anlageberatung.")
    return liste


def schreibe(e: dict, ordner: Path) -> list[Path]:
    stuecke = vorlesen.aufteilen(absaetze(e), vorlesen.stempel(datetime.fromisoformat(e["stand"])))
    pfade = vorlesen.schreibe_teile(ordner, "nachpruefer", stuecke)
    zeit = datetime.fromisoformat(e["stand"])
    lk = e["laufkontrolle"]
    zustand = "in Ordnung" if (lk.get("tage_mit_lauf") in (None, 7) and lk.get("zustand") != "Fehler") else "Warnung"
    status = (f"Agent: Nachprüfer (wöchentlich, GitHub)\n"
              f"Stand: {zeit.strftime('%d.%m.%Y, %H:%M')}\n"
              f"Zustand: {zustand}\n"
              f"Ergebnis: abgabe/nachpruefer-teil-1.md"
              + (f" bis nachpruefer-teil-{len(stuecke)}.md" if len(stuecke) > 1 else "")
              + ", daten/nachpruefer.json\n"
              f"Umfang: {len(stuecke)} Teil{'e' if len(stuecke) > 1 else ''}, "
              f"etwa {vorlesen.vorlesezeit_minuten(stuecke)} Minuten Vorlesezeit\n")
    speicher.schreibe_text(ordner / "status-nachpruefer.md", status)
    return pfade


def zusammenfassung(e: dict) -> str:
    lk = e["laufkontrolle"]
    zeilen = [f"## Nachprüfer, {e['stand']}", "",
              f"- Läufe in 7 Tagen: {lk.get('tage_mit_lauf')}, fehlend: {lk.get('fehlende_tage')}"]
    for r in e["rohstoffe"].values():
        a, sg = r["ampel"], r["signale"]
        zeilen.append(f"- {r['name']}: {a.get('farbe')} seit {a.get('seit')}; Signale {sg['anzahl']}, "
                      f"Treffer {sg['treffer']}, Fehlalarme {sg['fehlalarme']}, offen {sg['offen']}; "
                      f"Positionen offen {sum(p['offen'] for p in r['positionen'])}; "
                      f"Vorschlag fällig: {r['vorschlag_faellig']}")
    return "\n".join(zeilen) + "\n"
