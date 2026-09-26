"""Rechenwege des Metall-Agenten. Reine Funktionen ohne Netz, damit sie sich testen lassen.

Stufen je Achse: Grün = beobachten, Gelb = ein Vorbote ist da (Frist läuft aus,
US-Maßnahme, Störung an einem Standort). Rot setzt nur der Metall-Wächter in der Cloud,
wenn eine Meldung aus Peking dazukommt und die Preisprobe zeigt, dass der Markt schläft.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, timedelta
from statistics import mean

from .quellen import abstand_km


def tag(x) -> date | None:
    """YAML liefert Datumsangaben als date, JSON als Text; beides wird zu date."""
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


# ------------------------------------------------------------------ Wucht
def wucht(metall: dict) -> float:
    """Wuchtwert = Konzentration × Unersetzlichkeit (0 bis 1)."""
    return round(metall["konzentration"] * metall["unersetzlichkeit"], 2)


def achse_von_metallen(k: dict, metalle: list[str]) -> list[str]:
    achsen = []
    for m in metalle:
        a = (k["metalle"].get(m) or {}).get("achse")
        if a and a not in achsen:
            achsen.append(a)
    return achsen


# ------------------------------------------------------------------ Fristen
def fristen(liste: list[dict], heute: date, gelb_ab: int) -> list[dict]:
    """Tage bis zum Ablauf jeder Aussetzung. Ohne formelle Verlängerung ab `gelb_ab` Tagen Gelb."""
    ergebnis = []
    for f in liste or []:
        verlaengert = tag(f.get("verlaengert_bis"))
        bis = verlaengert or tag(f["bis"])
        rest = (bis - heute).days
        if rest < 0:
            zustand, gelb = "abgelaufen", True
        elif rest <= gelb_ab:
            zustand, gelb = "läuft bald aus", True
        else:
            zustand, gelb = "läuft", False
        ergebnis.append({"kennung": f["kennung"], "name": f["name"], "nummer": f.get("nummer"),
                         "achsen": list(f.get("achsen") or []), "bis": bis.isoformat(),
                         "urspruenglich_bis": tag(f["bis"]).isoformat(), "verlaengert": verlaengert is not None,
                         "tage": rest, "zustand": zustand, "gelb": gelb,
                         # läuft eine Aussetzung ohne neue Bekanntmachung aus, gelten die Kontrollen wieder
                         "rot_pruefen": zustand == "abgelaufen",
                         "stand": f.get("stand")})
    return ergebnis


# ------------------------------------------------------------------ Gegenseite
def _gewichtig(d: dict, regeln: list[dict], ausschluss: list[str]) -> bool:
    titel = (d.get("titel") or "").lower()
    if any(w.lower() in titel for w in ausschluss or []):
        return False
    for r in regeln or []:
        if "art" in r and d.get("art") != r["art"]:
            continue
        if "behoerde" in r and r["behoerde"] not in (d.get("behoerden") or []):
            continue
        if "arten" in r and d.get("art") not in r["arten"]:
            continue
        return True
    return False


def gegenseite(treffer: dict[str, list[dict]], g: dict, bekannt: set[str] | None = None) -> list[dict]:
    """Führt die Treffer je Suchbegriff zusammen, ordnet Achsen zu und markiert gewichtige und neue Einträge."""
    alle: dict[str, dict] = {}
    for begriff, dokumente in treffer.items():
        achsen_begriff = (g.get("begriffe") or {}).get(begriff) or []
        for d in dokumente:
            eintrag = alle.setdefault(d["nummer"], {**d, "begriffe": [], "achsen": []})
            eintrag["begriffe"].append(begriff)
            text = f"{d.get('titel', '')} {d.get('zusammenfassung', '')}".lower()
            achsen = list(achsen_begriff) or [a for a, woerter in (g.get("suchwoerter") or {}).items()
                                              if any(w.lower() in text for w in woerter)]
            for a in achsen:
                if a not in eintrag["achsen"]:
                    eintrag["achsen"].append(a)
    for e in alle.values():
        e["gewichtig"] = _gewichtig(e, g.get("gewichtig") or [], g.get("ausschluss_titel") or [])
        e["neu"] = bekannt is not None and e["nummer"] not in bekannt
    return sorted(alle.values(), key=lambda e: (e.get("datum") or "", e["nummer"]), reverse=True)


# ------------------------------------------------------------------ Störung
def erdbeben_treffer(beben: list[dict], standorte: list[dict], staffel: list[dict]) -> list[dict]:
    """Beben, die nach Stärke und Abstand einen Standort treffen können."""
    treffer = []
    for b in beben:
        for s in standorte:
            km = abstand_km(b["lat"], b["lon"], s["lat"], s["lon"])
            if any(b["staerke"] >= st["ab"] and km <= st["km"] for st in staffel):
                treffer.append({**b, "standort": s["kennung"], "standort_name": s["name"],
                                "metalle": list(s.get("metalle") or []), "abstand_km": round(km)})
    return treffer


def starkregen(regen: dict[str, dict], standorte: list[dict], heute: date, ab_mm: float) -> list[dict]:
    """Tage mit mindestens `ab_mm` Regen: gemessen (vor heute) oder vorhergesagt (ab heute)."""
    nach_kennung = {s["kennung"]: s for s in standorte}
    treffer = []
    for kennung, tage in regen.items():
        s = nach_kennung[kennung]
        for d, mm in sorted(tage.items()):
            if mm is None or mm < ab_mm:
                continue
            treffer.append({"standort": kennung, "standort_name": s["name"], "metalle": list(s.get("metalle") or []),
                            "datum": d, "mm": round(mm), "art": "gemessen" if d < heute.isoformat() else "vorhergesagt"})
    return treffer


def fuehre_stoerungen(alt: list[dict], neu: list[dict], heute: date, halten_tage: int) -> list[dict]:
    """Protokoll gemessener Störungen: neue kommen dazu, ältere als `2 × halten_tage` fallen weg."""
    grenze = (heute - timedelta(days=2 * halten_tage)).isoformat()
    schluessel = {(e["art"], e["standort"], e["datum"]): e for e in alt or []}
    for e in neu:
        schluessel[(e["art"], e["standort"], e["datum"])] = e
    return sorted((e for e in schluessel.values() if e["datum"] >= grenze), key=lambda e: e["datum"])


def normal_summe(klima: dict, tage: list[str]) -> float | None:
    """Summe der mittleren Tageswerte 1991–2020 über die gegebenen Tage (Schlüssel MM-TT)."""
    summen, anzahl = klima.get("summen") or {}, klima.get("anzahl") or {}
    werte = []
    for d in tage:
        mt = d[5:10]
        if not anzahl.get(mt):
            if mt == "02-29" and anzahl.get("02-28"):
                mt = "02-28"
            else:
                return None
        werte.append(summen[mt] / anzahl[mt])
    return sum(werte)


def klima_ergaenzen(klima: dict, jahr: int, tage: dict[str, float | None]) -> dict:
    """Nimmt ein Jahr Tageswerte ins Normal auf."""
    summen, anzahl = klima.setdefault("summen", {}), klima.setdefault("anzahl", {})
    for d, mm in tage.items():
        if mm is None or not d.startswith(str(jahr)):
            continue
        mt = d[5:10]
        summen[mt] = round(summen.get(mt, 0.0) + mm, 2)
        anzahl[mt] = anzahl.get(mt, 0) + 1
    fertig = set(klima.get("jahre_fertig") or [])
    fertig.add(jahr)
    klima["jahre_fertig"] = sorted(fertig)
    return klima


def trockenheit(ist: dict[str, float | None], klima: dict, fenster: int, unter: float,
                normal_ab: float) -> dict:
    """Regen der letzten `fenster` Tage mit Werten gegen das Normal derselben Tage."""
    gemessen = sorted(d for d, w in ist.items() if w is not None)[-fenster:]
    if len(gemessen) < fenster * 0.9:
        return {"urteil": "zu wenige Werte", "tage": len(gemessen)}
    normal = normal_summe(klima, gemessen)
    if normal is None:
        return {"urteil": "Normal fehlt"}
    summe = sum(ist[d] for d in gemessen)
    ergebnis = {"von": gemessen[0], "bis": gemessen[-1], "summe_mm": round(summe), "normal_mm": round(normal)}
    if normal < normal_ab:
        return {**ergebnis, "urteil": "Trockenzeit", "anteil": None, "trocken": False}
    anteil = summe / normal
    return {**ergebnis, "urteil": "trocken" if anteil < unter else "normal", "anteil": round(anteil, 2),
            "trocken": anteil < unter}


# ------------------------------------------------------------------ Kurse
def _index(reihe: list[dict], tag_text: str) -> int:
    return bisect_left([e["datum"] for e in reihe], tag_text)


def veraenderung(reihe: list[dict], tage: int) -> float | None:
    if len(reihe) <= tage:
        return None
    alt = reihe[-1 - tage]["schluss"]
    return reihe[-1]["schluss"] / alt - 1 if alt else None


def preisprobe(reihe: list[dict], vergleich: list[dict], p: dict, heute: date) -> dict:
    """Veränderung über kurze und lange Frist, und der Vorsprung gegen den Vergleichsmaßstab."""
    if not reihe:
        return {"urteil": "keine Kurse"}
    letzter = reihe[-1]
    ergebnis = {"letzter": letzter["datum"], "schluss": letzter["schluss"],
                "alter_tage": (heute - date.fromisoformat(letzter["datum"])).days}
    for name, t in (("kurz", p["tage_kurz"]), ("lang", p["tage_lang"])):
        eigen = veraenderung(reihe, t)
        ref = veraenderung(vergleich, t) if vergleich else None
        ergebnis[f"r_{name}"] = None if eigen is None else round(eigen, 4)
        ergebnis[f"vorsprung_{name}"] = None if eigen is None or ref is None else round(eigen - ref, 4)
    v = ergebnis["vorsprung_lang"]
    if ergebnis["alter_tage"] > 7:
        ergebnis["urteil"] = "veraltet"
    elif v is None:
        ergebnis["urteil"] = "ohne Vergleich"
    else:
        ergebnis["urteil"] = "gelaufen" if v >= p["gelaufen_ab"] else "schläft"
    ergebnis["markt_schlaeft"] = ergebnis["urteil"] == "schläft"
    return ergebnis


# ------------------------------------------------------------------ Ereignis-Rückblick
def ereignis_renditen(reihe: list[dict], ereignis_tag: date, horizonte: list[int], vorlauf: int) -> dict | None:
    """Renditen ab dem Schlusskurs vor dem Ereignis. Tag 0 ist der erste Handelstag ab dem Ankündigungstag."""
    if not reihe:
        return None
    i0 = _index(reihe, ereignis_tag.isoformat())
    if i0 == 0 or i0 >= len(reihe):
        return None
    vorher = date.fromisoformat(reihe[i0 - 1]["datum"])
    if (ereignis_tag - vorher).days > 10:           # der Wert wurde damals noch nicht gehandelt
        return None
    basis = reihe[i0 - 1]["schluss"]
    if not basis:
        return None
    ergebnis = {"tag0": reihe[i0]["datum"]}
    for h in horizonte:
        j = i0 + h
        ergebnis[f"r{h}"] = round(reihe[j]["schluss"] / basis - 1, 4) if j < len(reihe) else None
    k = i0 - 1 - vorlauf
    ergebnis["vorlauf"] = round(basis / reihe[k]["schluss"] - 1, 4) if k >= 0 and reihe[k]["schluss"] else None
    return ergebnis


def _vorsprung(eigen: dict, ref: dict | None, schluessel: str) -> float | None:
    if not ref or eigen.get(schluessel) is None or ref.get(schluessel) is None:
        return None
    return round(eigen[schluessel] - ref[schluessel], 4)


def rueckblick(ereignisse: list[dict], instrumente: list[dict], kurse: dict[str, list[dict]],
               vergleich: str, r: dict) -> dict:
    """Ereignisstudie: Wie liefen die Werte nach Verschärfungen, Lockerungen und US-Maßnahmen?"""
    horizonte, haupt, schwelle = r["horizonte"], r["haupt"], r["treffer_ab"]
    ref_reihe = kurse.get(vergleich) or []
    ergebnis = {}
    for inst in instrumente:
        reihe = kurse.get(inst["ticker"]) or []
        faelle = []
        for e in sorted(ereignisse, key=lambda e: tag(e["datum"])):
            d = tag(e["datum"])
            eigen = ereignis_renditen(reihe, d, horizonte, r["vorlauf"])
            if eigen is None:
                continue
            ref = ereignis_renditen(ref_reihe, d, horizonte, r["vorlauf"])
            fall = {"datum": d.isoformat(), "art": e["art"], "achsen": list(e.get("achsen") or []), "text": e["text"],
                    "eigene_achse": inst["achse"] in (e.get("achsen") or []), **eigen}
            for h in horizonte:
                fall[f"v{h}"] = _vorsprung(eigen, ref, f"r{h}")
            fall["v_vorlauf"] = _vorsprung(eigen, ref, "vorlauf")
            v = fall.get(f"v{haupt}")
            if v is not None:
                fall["treffer"] = v <= -schwelle if e["art"] == "lockerung" else v >= schwelle
            faelle.append(fall)
        gruppen = {}
        for art in ("verschaerfung", "lockerung", "gegenseite"):
            for bereich, auswahl in (("eigene", [f for f in faelle if f["art"] == art and f["eigene_achse"]]),
                                     ("alle", [f for f in faelle if f["art"] == art])):
                gruppen[f"{art}_{bereich}"] = _zusammenfassen(auswahl, horizonte, haupt)
        eigene = gruppen["verschaerfung_eigene"]
        b = r["bestanden"]
        if eigene["n"] < b["mindestens"]:
            urteil = "zu wenige Fälle"
        elif eigene["trefferquote"] >= b["trefferquote"] and (eigene.get(f"v{haupt}") or 0) > 0:
            urteil = "bestanden"
        else:
            urteil = "nicht bestanden"
        ergebnis[inst["ticker"]] = {"name": inst["name"], "achse": inst["achse"], "rolle": inst.get("rolle"),
                                    "erster_kurs": reihe[0]["datum"] if reihe else None,
                                    "urteil": urteil, "gruppen": gruppen, "faelle": faelle}
    return ergebnis


def _zusammenfassen(faelle: list[dict], horizonte: list[int], haupt: int) -> dict:
    mit = [f for f in faelle if f.get(f"v{haupt}") is not None]
    zusammen = {"n": len(mit), "offen": len(faelle) - len(mit)}
    for h in horizonte:
        werte = [f[f"v{h}"] for f in faelle if f.get(f"v{h}") is not None]
        zusammen[f"v{h}"] = round(mean(werte), 4) if werte else None
    vor = [f["v_vorlauf"] for f in faelle if f.get("v_vorlauf") is not None]
    zusammen["v_vorlauf"] = round(mean(vor), 4) if vor else None
    zusammen["treffer"] = sum(1 for f in mit if f.get("treffer"))
    zusammen["trefferquote"] = round(zusammen["treffer"] / len(mit), 2) if mit else 0.0
    return zusammen


# ------------------------------------------------------------------ Grundstufe
def grundstufe(k: dict, heute: date, fristen_liste: list[dict], dokumente: list[dict],
               beben: list[dict], regen_protokoll: list[dict], regen_voraus: list[dict],
               trocken: dict[str, dict]) -> dict[str, dict]:
    """Grün oder Gelb je Achse, mit Gründen. Mehrere Kanäle auf derselben Achse gelten als bestätigt."""
    halten = k["stoerung"]["gelb_tage"]
    grenze = (heute - timedelta(days=halten)).isoformat()
    gruende: dict[str, list[dict]] = {a: [] for a in k["achsen"]}

    def dazu(achsen, grund):
        for a in achsen:
            if a in gruende:
                gruende[a].append(grund)

    for f in fristen_liste:
        if f["gelb"]:
            dazu(f["achsen"], {"kanal": "frist", "kennung": f["kennung"], "tage": f["tage"], "zustand": f["zustand"]})
    for d in dokumente:
        if d["gewichtig"]:
            dazu(d["achsen"], {"kanal": "gegenseite", "nummer": d["nummer"], "datum": d["datum"], "titel": d["titel"]})
    for b in beben:
        dazu(achse_von_metallen(k, b["metalle"]),
             {"kanal": "erdbeben", "standort": b["standort"], "datum": b["datum"], "staerke": b["staerke"],
              "abstand_km": b["abstand_km"]})
    for e in regen_protokoll:
        if e["datum"] >= grenze:
            dazu(achse_von_metallen(k, e["metalle"]),
                 {"kanal": "starkregen", "standort": e["standort"], "datum": e["datum"], "mm": e["mm"], "art": "gemessen"})
    for e in regen_voraus:
        dazu(achse_von_metallen(k, e["metalle"]),
             {"kanal": "starkregen", "standort": e["standort"], "datum": e["datum"], "mm": e["mm"], "art": "vorhergesagt"})
    standorte = {s["kennung"]: s for s in k["standorte"]}
    for kennung, t in trocken.items():
        if t.get("trocken"):
            dazu(achse_von_metallen(k, standorte[kennung]["metalle"]),
                 {"kanal": "trocken", "standort": kennung, "anteil": t["anteil"]})

    ergebnis = {}
    for a, eintrag in k["achsen"].items():
        metalle = [{"kennung": m, "name": k["metalle"][m]["name"], "dativ": k["metalle"][m].get("dativ"),
                    "wucht": wucht(k["metalle"][m])}
                   for m in eintrag["metalle"]]
        kanaele = sorted({g["kanal"] for g in gruende[a]})
        ergebnis[a] = {"name": eintrag["name"], "beschreibung": eintrag.get("beschreibung"),
                       "pilot": bool(eintrag.get("pilot")), "metalle": metalle,
                       "wucht": max(m["wucht"] for m in metalle),
                       "stufe": "Gelb" if gruende[a] else "Grün", "gruende": gruende[a],
                       "kanaele": kanaele, "mehrfach": len({_familie(c) for c in kanaele}) > 1}
    return ergebnis


def _familie(kanal: str) -> str:
    """Erdbeben, Starkregen und Trockenheit sind derselbe Kanal (Störung)."""
    return "stoerung" if kanal in ("erdbeben", "starkregen", "trocken") else kanal


def reihenfolge(achsen: dict[str, dict]) -> list[str]:
    """Gelb vor Grün, darin nach Wucht; bei Gleichstand die Pilot-Achse zuerst."""
    return sorted(achsen, key=lambda a: (achsen[a]["stufe"] != "Gelb", -achsen[a]["wucht"], not achsen[a]["pilot"]))
