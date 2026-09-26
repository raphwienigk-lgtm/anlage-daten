"""Kalender der großen Marktberichte: was steht in den nächsten Tagen an?"""
from __future__ import annotations

import calendar
from datetime import date, timedelta


def _termine_im_zeitraum(bericht: dict, von: date, bis: date) -> list[date]:
    if bericht.get("termine"):
        termine = [t if isinstance(t, date) else date.fromisoformat(str(t)) for t in bericht["termine"]]
        return [t for t in termine if von <= t <= bis]
    tag = bericht.get("tag_im_monat")
    if not tag:
        return []
    treffer = []
    jahr, monat = von.year, von.month
    while date(jahr, monat, 1) <= bis:
        letzter = calendar.monthrange(jahr, monat)[1]
        termin = date(jahr, monat, min(tag, letzter))
        if von <= termin <= bis:
            treffer.append(termin)
        monat += 1
        if monat == 13:
            jahr, monat = jahr + 1, 1
    return treffer


def naechste(kalender: dict, heute: date) -> list[dict]:
    tage = (kalender or {}).get("vorschau_tage", 7)
    bis = heute + timedelta(days=tage)
    liste = []
    for bericht in (kalender or {}).get("berichte") or []:
        for termin in _termine_im_zeitraum(bericht, heute, bis):
            liste.append({"name": bericht["name"], "datum": termin.isoformat(),
                          "genau": bool(bericht.get("genau")), "rohstoffe": bericht.get("rohstoffe", [])})
    return sorted(liste, key=lambda e: e["datum"])
