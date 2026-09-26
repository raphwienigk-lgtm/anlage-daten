"""Signal-Logbuch: jede Farbänderung einer Ampel mit Datum, Grund und Kursen.

Eine Zeile je Ereignis in daten/signale.jsonl. Wird nie umgeschrieben, nur ergänzt.
Grundlage für den Nachprüfer (Wochenbilanz) und das Schattendepot: Springt eine Ampel
auf Rot, gilt das als gedachter Kauf zu den hier festgehaltenen Kursen. Kaputte Zeilen
(etwa nach einem Konflikt beim Zusammenführen) werden beim Lesen übersprungen.
"""
from __future__ import annotations

import json
from pathlib import Path


def lies(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    eintraege = []
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                eintraege.append(json.loads(zeile))
            except json.JSONDecodeError:
                continue
    return eintraege


def letzter_stand(eintraege: list[dict]) -> dict[str, dict]:
    stand = {}
    for e in eintraege:
        stand[e["rohstoff"]] = e
    return stand


def offene_schattenpositionen(eintraege: list[dict]) -> set[str]:
    """Rohstoffe mit gedachtem Kauf, der noch nicht geschlossen ist."""
    offen = set()
    for e in eintraege:
        if e.get("schattenkauf"):
            offen.add(e["rohstoff"])
        if e.get("schattenschluss"):
            offen.discard(e["rohstoff"])
    return offen


def ergaenze(pfad: Path, zeit: str, bewertungen: dict[str, dict]) -> list[dict]:
    """Schreibt für jeden Rohstoff eine Zeile, wenn sich Farbe oder Veto-Sperre geändert hat.

    - Beim ersten Lauf entsteht je Rohstoff eine Startzeile.
    - Mehrere Läufe ohne Änderung schreiben nichts.
    - „ohne Urteil“ (Auslöser nicht lesbar) schreibt nichts und ändert nichts.
    - Schattendepot: Rot ohne Sperre eröffnet einen gedachten Kauf, wenn keiner offen ist.
      Bis der Ausstiegs-Beobachter steht, schließt erst die Rückkehr auf Grün ihn.
    """
    alle = lies(pfad)
    bisher = letzter_stand(alle)
    offen = offene_schattenpositionen(alle)
    neu = []
    for kennung, b in bewertungen.items():
        ampel = b.get("ampel")
        if not ampel or ampel["farbe"] not in ("Grün", "Gelb", "Rot"):
            continue
        vorher = bisher.get(kennung)
        farbe = ampel["farbe"]
        vorher_farbe = vorher["farbe"] if vorher else None
        if vorher and vorher_farbe == farbe and vorher.get("gesperrt") == ampel["gesperrt"]:
            continue
        if not vorher:
            anlass = "Start"
        elif vorher_farbe == farbe:
            anlass = "Veto gesetzt" if ampel["gesperrt"] else "Veto aufgehoben"
        else:
            anlass = "Farbwechsel"
        preis = b.get("preisprobe", {}).get("letzter")
        neu.append({
            "zeit": zeit,
            "rohstoff": kennung,
            "farbe": farbe,
            "zahl": ampel.get("zahl"),
            "gesperrt": ampel["gesperrt"],
            "vorher": vorher_farbe,
            "anlass": anlass,
            "gruende": ampel.get("gruende", []),
            "schattenkauf": farbe == "Rot" and not ampel["gesperrt"] and kennung not in offen,
            "schattenschluss": farbe == "Grün" and kennung in offen,
            "rohstoffpreis": preis,
            "kurse": {i["ticker"]: {"kurs": i.get("kurs"), "datum": i.get("datum")}
                      for i in b.get("instrumente", []) if i.get("kurs") is not None},
        })
    if neu:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with open(pfad, "a", encoding="utf-8") as f:
            for e in neu:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return neu
