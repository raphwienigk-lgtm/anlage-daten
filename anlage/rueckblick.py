"""Rückblick: die Ampel als Zeitmaschine über die Geschichte laufen lassen.

Für jeden Monat ab 1960 wird die Ampel so gerechnet, als wäre heute der 15. dieses
Monats, nur mit den Daten, die an dem Tag schon veröffentlicht waren (Verzug in
schwellen.yaml unter rueckblick.verzug):
- El-Niño-Index: eine Jahreszeit gilt zwei Monate nach ihrer Mitte (JAS ab Oktober).
- Dipol-Index: der Vormonat. Preis des Rohstoffs: zwei Monate zurück wie FRED im
  täglichen Lauf. Gegenkräfte: Monatsdurchschnitt des Vormonats statt Tageskurs.
- Regen: bis sechs Tage vor dem Stichtag.
- Ostwinde Mai und Juni: erst ab Juli, dann als ganzes Jahr.
Gerechnet wird mit denselben Modulen wie im täglichen Lauf. Politik-Veto und
Handeingaben gibt es im Rückblick nicht.

Lernzeit (bis rueckblick.lernzeit_bis): Hier darf man lernen. Preise dahinter bleiben
auch für die Bilanz der Lernzeit unberührt. Prüfzeit danach: bleibt verschlossen, bis
sie bewusst geöffnet wird (--pruefzeit-oeffnen). Jedes Öffnen wird mit einem
Fingerabdruck der Regeln festgehalten; maßgeblich ist das erste. Wer danach Regeln
ändert und wieder öffnet, bekommt den Vermerk, dass die Prüfzeit nicht mehr unabhängig ist.

Aufruf: python -m anlage.rueckblick [--rohstoff palmoel] [--pruefzeit-oeffnen] [--ohne-varianten]
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import inspect
import json
import os
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean

from . import __version__, bilanz, geschichte, klimatologie, konfig, netz, speicher
from .ausgabe import rueckblick_text
from .lauf import regenbedarf_ab
from .module import dipol, enso, regenzeugen
from .quellen import klimaindizes
from .rechnen import bewerten

HINWEIS = "Denkhilfe, keine Anlageberatung."
REGELCODE = ["anlage/module/enso.py", "anlage/module/dipol.py", "anlage/module/regenzeugen.py",
             "anlage/rechnen/bewerten.py", "anlage/rechnen/kennzahlen.py", "anlage/bilanz.py"]
MINDEST_ABDECKUNG = 0.9          # Anteil gemessener Tage, ab dem ein Jahr als vollständig gilt
MAX_LUECKENJAHRE = 2             # mehr unvollständige Jahre je Punkt: kein Rückblick


class Fehlt(Exception):
    """Ohne diese Daten ist kein ehrlicher Rückblick möglich."""


# ------------------------------------------------------------------ Daten
class Regenarchiv:
    """Tagesregen je Punkt, mit schnellem Ausschnitt nach Datum."""

    def __init__(self, punkte: dict[str, dict[str, float]]):
        self.werte = punkte
        self.tage = {n: sorted(w) for n, w in punkte.items()}

    def ausschnitt(self, namen: list[str], von: date, bis: date) -> dict[str, dict[str, float]]:
        a, b = von.isoformat(), bis.isoformat()
        ergebnis = {}
        for n in namen:
            tage = self.tage.get(n, [])
            werte = self.werte.get(n, {})
            ergebnis[n] = {t: werte[t] for t in tage[bisect_left(tage, a):bisect_right(tage, b)]}
        return ergebnis


@dataclass
class Geschichte:
    oni: list[dict]
    dmi: list[dict] | None
    dmi_quelle: str | None
    regen: Regenarchiv
    regen_normal: dict
    ost: list[str]
    west: list[str]
    wind_normal: dict[str, float]
    wind_je_jahr: dict[str, dict[int, float]]
    wind_tage: int
    preise: dict[str, list[dict]]
    preis_herkunft: dict[str, str]
    ernte: dict | None
    hinweise: list[str] = field(default_factory=list)
    herkunft: dict = field(default_factory=dict)

    def __post_init__(self):
        self.oni_idx = [e["jahr"] * 12 + e["monat"] - 1 for e in self.oni]
        self.dmi_idx = [e["jahr"] * 12 + e["monat"] - 1 for e in self.dmi or []]

    def wind_fuer(self, jahre: list[int], heute: date, ab_monat: int) -> dict[int, dict]:
        ergebnis = {}
        for jahr in jahre:
            if jahr > heute.year or (jahr == heute.year and heute.month < ab_monat):
                continue                                   # noch nicht bekannt: Stufe zwei ohne Urteil
            abweichungen = [self.wind_je_jahr[n][jahr] - normal for n, normal in self.wind_normal.items()
                            if jahr in self.wind_je_jahr.get(n, {})]
            if not abweichungen:
                ergebnis[jahr] = {"fehler": "keine Winddaten für dieses Jahr"}
                continue
            ergebnis[jahr] = {"anomalie_ms": round(mean(abweichungen), 2), "tage": self.wind_tage,
                              "vollstaendig": True, "bis": f"{jahr}-06-30"}
        return ergebnis


def _oni(q: dict, hinweise: list[str], herkunft: dict) -> list[dict]:
    try:
        reihe = klimaindizes.hole_oni(q["oni"]["url"])
        herkunft["oni"] = f"{q['oni']['name']}, heute geholt"
        return reihe
    except Exception as fehler:
        ablage = speicher.lies_json(konfig.KLIMA / "oni.json") or {}
        if not ablage.get("reihe"):
            raise Fehlt(f"El-Niño-Index nicht erreichbar ({fehler}) und nicht gespeichert")
        hinweise.append(f"El-Niño-Index heute nicht erreichbar, es gilt der gespeicherte Stand vom {ablage.get('geholt')}.")
        herkunft["oni"] = f"{q['oni']['name']}, gespeichert am {ablage.get('geholt')}"
        return ablage["reihe"]


def _dmi(q: dict, beginn_jahr: int, hinweise: list[str], herkunft: dict) -> tuple[list[dict] | None, str | None]:
    """Dieselbe Quelle wie im täglichen Lauf, damit die Schwelle an derselben Reihe geprüft wird.
    Reicht sie nicht bis `beginn_jahr` zurück, gilt die nächste Quelle, die es tut, sonst die längste."""
    ablage = speicher.lies_json(konfig.KLIMA / "dmi.json") or {}
    live = ablage.get("quelle")
    reihen, fehler = {}, []
    for eintrag in q["dmi"]["urls"]:
        try:
            reihen[eintrag["name"]] = klimaindizes.lies_monatsreihe(netz.hole_text(eintrag["url"]))
        except Exception as f:
            fehler.append(f"{eintrag['name']}: {f}")
    if live and live not in reihen and ablage.get("reihe"):
        reihen[live] = ablage["reihe"]
        hinweise.append(f"Dipol-Index {live} heute nicht erreichbar, es gilt der gespeicherte Stand.")
    if not reihen:
        hinweise.append("Dipol-Index fehlt ganz: Stufe drei bleibt ohne Urteil. " + "; ".join(fehler))
        return None, None
    reihenfolge = ([live] if live in reihen else []) + [e["name"] for e in q["dmi"]["urls"]
                                                         if e["name"] in reihen and e["name"] != live]
    name = next((n for n in reihenfolge if reihen[n][0]["jahr"] <= beginn_jahr),
                min(reihenfolge, key=lambda n: (reihen[n][0]["jahr"], reihen[n][0]["monat"])))
    reihe = reihen[name]
    if live and name != live:
        hinweise.append(f"Dipol-Index: {live} reicht nur bis {reihen[live][0]['jahr'] if live in reihen else '?'} "
                        f"zurück; der Rückblick nutzt {name}, der tägliche Lauf {live}.")
    if reihe[0]["jahr"] > beginn_jahr:
        hinweise.append(f"Dipol-Index beginnt erst {reihe[0]['jahr']}; davor bleibt Stufe drei ohne Urteil.")
    herkunft["dmi"] = f"{name}, ab {reihe[0]['jahr']}, bis {reihe[-1]['jahr']}-{reihe[-1]['monat']:02d}"
    return reihe, name


def _abdeckung(werte: dict, jahr: int, monate: list[int] | None, von: date, bis: date) -> float | None:
    """Anteil der Tage eines Jahres (nur `monate`, nur zwischen von und bis) mit Messwert."""
    tage = vorhanden = 0
    tag = max(date(jahr, 1, 1), von)
    ende = min(date(jahr, 12, 31), bis)
    while tag <= ende:
        if monate is None or tag.month in monate:
            tage += 1
            vorhanden += tag.isoformat() in werte
        tag += timedelta(days=1)
    return vorhanden / tage if tage else None


def lade(k: dict, rohstoff: dict, von: date, bis: date) -> Geschichte:
    """Liest alle Geschichtsdaten und prüft, ob sie für einen ehrlichen Rückblick reichen."""
    hinweise, herkunft = [], {}
    status = speicher.lies_json(konfig.GESCHICHTE / "status.json", {}) or {}
    offen = [t for t in ("preise", "regen", "wind") if not (status.get(t) or {}).get("fertig")]
    if offen:
        raise Fehlt("Geschichtsdaten noch nicht vollständig (" + ", ".join(offen) + "). "
                    "Erst den Workflow „Geschichte“ fertig laufen lassen.")
    q, regionen = k["quellen"], k["regionen"]

    regen_normal = speicher.lies_json(konfig.KLIMA / "regen.json") or {}
    regenpunkte = regionen["ost"]["punkte"] + regionen["west"]["punkte"]
    fehlend = [p["name"] for p in regenpunkte if not klimatologie.ist_fertig(regen_normal, p)]
    wind_klima = speicher.lies_json(konfig.KLIMA / "wind.json") or {}
    fehlend += [p["name"] for p in regionen["wind_sumatra"]["punkte"] if not klimatologie.ist_fertig(wind_klima, p)]
    if fehlend:
        raise Fehlt("Klimatologie unvollständig (" + ", ".join(fehlend) + "). Erst den Workflow „Klimatologie“ fertig laufen lassen.")

    # Regen: Geschichte, ergänzt um das Archiv des täglichen Laufs
    ist = (speicher.lies_json(konfig.KLIMA / "regen_ist.json", {}) or {}).get("punkte", {})
    monate_west = k["schwellen"]["zeugen"]["west"]["monate"]
    punkte = {}
    for region in ("ost", "west"):
        for p in regionen[region]["punkte"]:
            daten = geschichte.lies_gz(geschichte.regen_pfad(p["name"])) or {}
            if daten.get("ort") and daten["ort"] != {"lat": p["lat"], "lon": p["lon"]}:
                raise Fehlt(f"Regen {p['name']}: Der Messpunkt wurde verschoben. Erst den Workflow „Geschichte“ "
                            "noch einmal laufen lassen.")
            werte = {t: w for t, w in (daten.get("werte") or {}).items() if w is not None}
            werte.update({t: w for t, w in (ist.get(p["name"]) or {}).items() if w is not None})
            if not werte:
                raise Fehlt(f"Regen für {p['name']} fehlt in der Geschichte. Erst den Workflow „Geschichte“ laufen lassen.")
            punkte[p["name"]] = werte
            regen_von = von - timedelta(days=90)
            luecken = [j for j in range(regen_von.year, bis.year + 1)
                       if (a := _abdeckung(werte, j, None if region == "ost" else monate_west, regen_von, bis)) is not None
                       and a < MINDEST_ABDECKUNG]
            if len(luecken) > MAX_LUECKENJAHRE:
                raise Fehlt(f"Regen {p['name']}: Lücken in {len(luecken)} Jahren ({luecken[0]} bis {luecken[-1]}). "
                            "Erst den Workflow „Geschichte“ fertig laufen lassen.")
            if luecken:
                hinweise.append(f"Regen {p['name']}: Lücken in {len(luecken)} Jahren ({', '.join(map(str, luecken))}).")
    herkunft["regen"] = f"Open-Meteo ERA5, {len(punkte)} Punkte"

    # Wind: Geschichte, Klimatologie 1991 bis 2020, Archiv des täglichen Laufs
    wind_normal = {n: e["mittel_ms"] for n, e in (wind_klima.get("punkte") or {}).items()}
    w_gesch_daten = speicher.lies_json(konfig.GESCHICHTE / "wind.json", {}) or {}
    w_gesch = w_gesch_daten.get("punkte", {})
    w_orte = w_gesch_daten.get("orte", {})
    w_ist = (speicher.lies_json(konfig.KLIMA / "wind_ist.json", {}) or {}).get("jahre", {})
    je_jahr = {}
    for p in regionen["wind_sumatra"]["punkte"]:
        n = p["name"]
        reihe = {int(j): u for j, u in ((wind_klima["punkte"].get(n) or {}).get("je_jahr") or {}).items()}
        if w_orte.get(n, {"lat": p["lat"], "lon": p["lon"]}) != {"lat": p["lat"], "lon": p["lon"]}:
            raise Fehlt(f"Wind {n}: Der Messpunkt wurde verschoben. Erst den Workflow „Geschichte“ noch einmal laufen lassen.")
        reihe.update({int(j): u for j, u in ((w_gesch.get(n) or {}).get("je_jahr") or {}).items()})
        reihe.update({int(j): e["punkte"][n] for j, e in w_ist.items()
                      if e.get("vollstaendig") and n in (e.get("punkte") or {})})
        je_jahr[n] = reihe
        fehlt = [j for j in range(von.year, bis.year + 1) if j not in reihe and date(j, 7, 10) <= bis]
        if fehlt:
            hinweise.append(f"Wind {n}: {len(fehlt)} Jahre fehlen ({fehlt[0]} bis {fehlt[-1]}).")
    monate = k["schwellen"]["dipol"]["wind_monate"]
    wind_tage = sum(calendar.monthrange(2001, m)[1] for m in range(monate[0], monate[-1] + 1))

    # Preise
    preisdaten = speicher.lies_json(konfig.GESCHICHTE / "preise.json") or {}
    reihen = {kennung: sorted((e for e in reihe if e.get("wert")), key=lambda e: e["datum"])
              for kennung, reihe in (preisdaten.get("reihen") or {}).items()}
    if not reihen.get(rohstoff["kennung"]):
        raise Fehlt(f"Preisreihe für {rohstoff['name']} fehlt in der Geschichte.")
    for g in rohstoff.get("gegenkraefte", []):
        if not reihen.get(g["kennung"]):
            hinweise.append(f"Gegenkraft {g.get('text', g['kennung'])}: keine Preisreihe, Punkt drei rechnet ohne sie.")
    herkunft["preise"] = preisdaten.get("herkunft") or {}

    oni = sorted(_oni(q, hinweise, herkunft), key=lambda e: (e["jahr"], e["monat"]))
    dmi, dmi_quelle = _dmi(q, von.year, hinweise, herkunft)
    return Geschichte(
        oni=oni, dmi=dmi, dmi_quelle=dmi_quelle,
        regen=Regenarchiv(punkte), regen_normal=regen_normal,
        ost=[p["name"] for p in regionen["ost"]["punkte"]], west=[p["name"] for p in regionen["west"]["punkte"]],
        wind_normal=wind_normal, wind_je_jahr=je_jahr, wind_tage=wind_tage,
        preise=reihen, preis_herkunft=preisdaten.get("herkunft") or {},
        ernte=speicher.lies_json(konfig.GESCHICHTE / "ernte.json"),
        hinweise=hinweise, herkunft=herkunft,
    )


# ------------------------------------------------------------------ Zeitmaschine
def _bis(reihe: list[dict], idx_liste: list[int], grenze: int) -> list[dict]:
    return reihe[:bisect_right(idx_liste, grenze)]


def _eintrag(i: int, b: dict, enso_lage: dict | None, dipol_lage: dict | None) -> dict:
    ampel = b["ampel"]
    fehlt = []
    for c in ampel.get("rot_bedingungen") or []:
        if c["erfuellt"] is False:
            fehlt.append(c["name"])
        elif c["erfuellt"] is None:
            fehlt.append(f"{c['name']} (ohne Daten)")
    return {
        "monat": bilanz.monat_text(i),
        "farbe": ampel["farbe"],
        "zahl": ampel.get("zahl"),
        "episode": bool((enso_lage or {}).get("episode")),
        "oni": (enso_lage or {}).get("aktuell", {}).get("wert"),
        "zf": b["zeitfenster"]["wert"],
        "z": b["preisprobe"]["z"],
        "gegen": b["gegenkraefte"]["wert"],
        "ostende": dipol_lage["ostende_bestaetigt"] if dipol_lage else None,
        "kreuz": dipol_lage["kreuz"]["urteil"] if dipol_lage else None,
        "fehlt": fehlt,
    }


def zeitmaschine(g: Geschichte, rohstoff: dict, k: dict, von: int, bis: int) -> list[dict]:
    """Ampel je Monat von `von` bis `bis` (Monatsnummern), Stichtag jeweils der 15."""
    s = k["schwellen"]
    verzug = s["rueckblick"]["verzug"]
    # Gegenkräfte als Monatswerte zum Ersten: 89 Tage treffen genau drei Monate zurück
    s_bewerten = {**s, "agrar_ampel": {**s["agrar_ampel"], "gegen_tage": 89}}
    T = rohstoff["vorlauf_T_monate"]
    mit_dipol = "dipol" in rohstoff.get("kopplungen", [])
    preis = g.preise[rohstoff["kennung"]]
    preis_idx = [bilanz.monats_index(e["datum"]) for e in preis]
    gegen = {}
    for gk in rohstoff.get("gegenkraefte", []):
        reihe = g.preise.get(gk["kennung"]) or []
        gegen[gk["kennung"]] = ([{"datum": e["datum"], "schluss": e["wert"]} for e in reihe],
                                [bilanz.monats_index(e["datum"]) for e in reihe])
    verlauf = []
    for i in range(von, bis + 1):
        heute = date(i // 12, i % 12 + 1, 15)
        oni = _bis(g.oni, g.oni_idx, i - verzug["oni_monate"])
        if not oni:
            verlauf.append({"monat": bilanz.monat_text(i), "farbe": bewerten.OHNE_URTEIL, "fehlt": []})
            continue
        enso_lage = enso.lage(oni, s["enso"], heute, T)
        ep_ab, ep_bis = enso.episode_beginn(enso_lage), enso.zaehlt_bis(enso_lage)
        dmi = _bis(g.dmi, g.dmi_idx, i - verzug["dmi_monate"]) if g.dmi else None

        regen_von = regenbedarf_ab(heute, ep_ab, s["zeugen"]["west"]["monate"])
        regen_bis = heute - timedelta(days=verzug["regen_tage"])
        zeugen = regenzeugen.zeugen(g.regen.ausschnitt(g.ost, regen_von, regen_bis),
                                    g.regen.ausschnitt(g.west, regen_von, regen_bis),
                                    g.regen_normal, s["zeugen"], heute, ep_ab, ep_bis)
        ep_jahre = enso.episode_jahre(enso_lage, heute)
        wind_monate = s["dipol"]["wind_monate"]
        noetig = sorted(set(ep_jahre) | ({heute.year} if heute.month >= wind_monate[0] else set()))
        wind = g.wind_fuer(noetig, heute, verzug["wind_ab_monat"])
        dipol_lage = dipol.lage(enso_lage, ep_ab, ep_bis, ep_jahre, dmi or None, g.dmi_quelle, wind, zeugen,
                                {}, heute, s["dipol"])

        preisreihe = _bis(preis, preis_idx, i - verzug["preis_monate"])
        gegen_reihen = {kennung: _bis(reihe, idx, i - verzug["gegen_monate"]) for kennung, (reihe, idx) in gegen.items()}
        b = bewerten.bewerte(rohstoff, enso_lage, dipol_lage if mit_dipol else None, preisreihe or None,
                             gegen_reihen, {}, {}, s_bewerten, {}, heute)
        verlauf.append(_eintrag(i, b, enso_lage, dipol_lage if mit_dipol else None))
    return verlauf


# ------------------------------------------------------------------ Auswertung
RANG = {"Grün": 0, "Gelb": 1, "Rot": 2}


def _ernte_probe(ernte: dict | None, jahr: int, bis_jahr: int) -> dict | None:
    """Produktion Indonesien plus Malaysia: schwächstes Wachstum im Wirtschaftsjahr des
    Höhepunkts und im folgenden, verglichen mit dem mittleren Wachstum der fünf Jahre davor.
    Jahre nach `bis_jahr` bleiben weg (keine Ernte aus der Prüfzeit in der Lernzeit)."""
    reihen = (ernte or {}).get("reihen") or {}
    if not reihen:
        return None
    summe = Counter()
    for werte in reihen.values():
        for j, w in werte.items():
            if int(j) <= bis_jahr:
                summe[int(j)] += w
    wachstum = {j: summe[j] / summe[j - 1] - 1 for j in summe if summe.get(j - 1)}
    vorher = [wachstum[j] for j in range(jahr - 5, jahr) if j in wachstum]
    danach = [(wachstum[j], j) for j in (jahr, jahr + 1) if j in wachstum]
    if len(vorher) < 3 or not danach:
        return None
    tief, tief_jahr = min(danach)
    return {"jahr": tief_jahr, "wachstum": round(tief, 4), "vorher_mittel": round(mean(vorher), 4),
            "delle": round(tief - mean(vorher), 4)}


def episoden_blick(g: Geschichte, verlauf: list[dict], preisreihe: list[dict], k: dict, T: int,
                   von: int, bis: int) -> list[dict]:
    """Je El-Niño-Episode mit Höhepunkt im Zeitraum: höchste Farbe, Preis danach, Engpass, Ernte."""
    nach_monat = {bilanz.monats_index(e["monat"]): e for e in verlauf}
    preise = bilanz.preis_nach_monat(preisreihe, bis)
    liste = []
    for ep in enso.episoden(_oni_bis(g, bis), k["schwellen"]["enso"]):
        h = ep["hoehepunkt"]
        hi = h["jahr"] * 12 + h["monat"] - 1
        if not von <= hi <= bis:
            continue
        b = ep["beginn"]
        start = max(von, b["jahr"] * 12 + b["monat"] - 2)
        ende = min(bis, hi + T + 6)
        fenster = [nach_monat[j] for j in range(start, ende + 1) if j in nach_monat]
        farbig = [e for e in fenster if e["farbe"] in RANG]
        beste = max((RANG[e["farbe"]] for e in farbig), default=None)
        erste = next((e["monat"] for e in farbig if RANG[e["farbe"]] == beste), None) if beste is not None else None
        engpass = Counter(n for e in fenster if e["farbe"] == "Gelb" for n in e.get("fehlt") or [])
        anstieg = None
        if hi in preise:
            spaeter = [(preise[j], j) for j in range(hi + 1, ende + 1) if j in preise]
            if spaeter:
                w, j = max(spaeter, key=lambda x: (x[0], -x[1]))
                anstieg = {"wert": round(w / preise[hi] - 1, 4), "monat": bilanz.monat_text(j)}
        liste.append({
            "beginn": f"{b['jahreszeit']} {b['jahr']}", "hoehepunkt": h,
            "hoechste_farbe": [k_ for k_, v in RANG.items() if v == beste][0] if beste is not None else None,
            "erster_monat": erste,
            "engpass": engpass.most_common(1)[0][0] if engpass else None,
            "preis_nach_hoehepunkt": anstieg,
            "ernte": _ernte_probe(g.ernte, h["jahr"], bis // 12),
        })
    return liste


def _oni_bis(g: Geschichte, bis: int) -> list[dict]:
    return _bis(g.oni, g.oni_idx, bis)


def hoehepunkte(g: Geschichte, k: dict, bis: int) -> list[int]:
    """Monatsnummern der El-Niño-Höhepunkte bis `bis`, im Nachhinein bestimmt (nur zur Einordnung
    großer Preisbewegungen, nie für die Ampel selbst)."""
    return [e["hoehepunkt"]["jahr"] * 12 + e["hoehepunkt"]["monat"] - 1
            for e in enso.episoden(_oni_bis(g, bis), k["schwellen"]["enso"])]


def _kurz(b: dict) -> dict:
    felder = ("von", "bis", "monate", "farben", "anzahl", "bewertbar", "treffer", "fehlalarme", "offen",
              "mittel_12", "basis_12", "basis_trefferquote", "mehrwert", "zufall_anteil", "urteil",
              "bewegungen_zaehlung", "engpaesse")
    return {**{f: b.get(f) for f in felder}, "signale": [s["monat"] for s in b.get("signale", [])]}


def fingerabdruck(k: dict, rohstoff: dict, dmi_quelle: str | None = None) -> str:
    """Fingerabdruck der Regeln und ihrer Grundlage: Schwellen, Regionen, Formular, Quelle des
    Dipol-Index, der Code der Rechenwege und der Zeitmaschine."""
    regeln = {
        "schwellen": {s: v for s, v in k["schwellen"].items() if s != "kurse"},
        "regionen": k["regionen"],
        "rohstoff": {s: v for s, v in rohstoff.items() if s != "instrumente"},
        "dmi_quelle": dmi_quelle,
    }
    h = hashlib.sha256(json.dumps(regeln, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    for pfad in REGELCODE:
        h.update((konfig.BASIS / pfad).read_bytes())
    for teil in (zeitmaschine, _eintrag, _bis, Regenarchiv.ausschnitt, Geschichte.wind_fuer, regenbedarf_ab):
        h.update(inspect.getsource(teil).encode("utf-8"))
    return h.hexdigest()[:16]


def _monat(text) -> int:
    return bilanz.monats_index(str(text))


def rueckblick(k: dict, kennung: str, zeitpunkt: datetime, pruefzeit_oeffnen: bool = False,
               mit_varianten: bool = True, melde=print) -> dict:
    if kennung not in k["rohstoffe"]:
        raise Fehlt(f"Rohstoff „{kennung}“ hat kein Formular in konfig/rohstoffe.")
    r = {**k["rohstoffe"][kennung], "instrumente": []}
    fehler = konfig.pruefe_rohstoff(r, k["regionen"])
    if fehler:
        raise Fehlt("Formular fehlerhaft: " + "; ".join(fehler))
    if r["treiber"] != "klima" or r.get("ausloeser") != "enso":
        raise Fehlt(f"Für Treiber „{r['treiber']}“ gibt es noch keinen Rechenweg, also auch keinen Rückblick.")
    s_rb = k["schwellen"]["rueckblick"]
    heute = zeitpunkt.date()
    letzter = heute.year * 12 + heute.month - 2            # letzter vollständig vergangener Monat
    lern_bis = min(_monat(s_rb["lernzeit_bis"]), letzter)
    beginn = _monat(s_rb["beginn"])
    ende_daten = letzter if pruefzeit_oeffnen else lern_bis
    g = lade(k, r, date(beginn // 12, beginn % 12 + 1, 1),
             date(ende_daten // 12, ende_daten % 12 + 1, 28))
    preisreihe = g.preise[kennung]
    von = max(beginn, bilanz.monats_index(preisreihe[0]["datum"]))
    if von > beginn:
        g.hinweise.append(f"Die Preisreihe beginnt erst {bilanz.monat_text(von)}; so spät beginnt auch der Rückblick "
                          f"({g.preis_herkunft.get(kennung, 'Quelle unbekannt')}).")
    if von > lern_bis:
        raise Fehlt("Die Preisreihe beginnt erst nach dem Ende der Lernzeit.")
    melde(f"Zeitmaschine {r['name']}: {bilanz.monat_text(von)} bis {bilanz.monat_text(lern_bis)} …")
    von_t, bis_t = bilanz.monat_text(von), bilanz.monat_text(lern_bis)

    T = r["vorlauf_T_monate"]
    ereignisse = hoehepunkte(g, k, lern_bis)
    verlauf = zeitmaschine(g, r, k, von, lern_bis)
    haupt = bilanz.bilanz(verlauf, preisreihe, von_t, bis_t, s_rb, preis_bis=bis_t,
                          ereignisse=ereignisse, ereignis_fenster=(-3, T))
    zeitalter = []
    grenze_jahr = int(s_rb.get("wetter_unsicher_bis", 1978))
    grenze = grenze_jahr * 12 + 11
    if von <= grenze < lern_bis:
        zeitalter = [
            {"name": f"bis {grenze_jahr}", "bilanz": _kurz(bilanz.bilanz(
                verlauf, preisreihe, von_t, bilanz.monat_text(grenze), s_rb, bis_t, ereignisse, (-3, T)))},
            {"name": f"ab {grenze_jahr + 1}", "bilanz": _kurz(bilanz.bilanz(
                verlauf, preisreihe, bilanz.monat_text(grenze + 1), bis_t, s_rb, bis_t, ereignisse, (-3, T)))},
        ]
    varianten = []
    if mit_varianten:
        for v in s_rb.get("varianten") or []:
            melde(f"Variante: {v['name']} …")
            rv = {**r, "vorlauf_T_monate": v["vorlauf_T_monate"]}
            vb = bilanz.bilanz(zeitmaschine(g, rv, k, von, lern_bis), preisreihe, von_t, bis_t, s_rb, preis_bis=bis_t,
                               ereignisse=ereignisse, ereignis_fenster=(-3, v["vorlauf_T_monate"]))
            varianten.append({"name": v["name"], "vorlauf_T_monate": v["vorlauf_T_monate"], "bilanz": _kurz(vb)})

    abdruck = fingerabdruck(k, r, g.dmi_quelle)
    _grenze_pruefen(kennung, s_rb["lernzeit_bis"], abdruck, haupt, heute, g.hinweise)
    pruefzeit = _pruefzeit(g, r, k, kennung, lern_bis, letzter, abdruck, pruefzeit_oeffnen, preisreihe, verlauf,
                           heute, melde)
    return {
        "stand": zeitpunkt.isoformat(timespec="seconds"),
        "version": __version__,
        "hinweis": HINWEIS,
        "rohstoff": kennung,
        "name": r["name"],
        "fingerabdruck": abdruck,
        "einstellungen": {
            "beginn": s_rb["beginn"], "von": von_t, "lernzeit_bis": bis_t,
            "vorlauf_T_monate": r["vorlauf_T_monate"],
            **{f: s_rb.get(f) for f in ("treffer_ab", "bewegung_ab", "erkannt_monate_vorher", "bestehen",
                                        "verzug", "wetter_unsicher_bis")},
        },
        "daten": {"herkunft": g.herkunft, "hinweise": g.hinweise},
        "lernzeit": {
            "bilanz": haupt,
            "zeitalter": zeitalter,
            "episoden": episoden_blick(g, verlauf, preisreihe, k, T, von, lern_bis),
            "verlauf": verlauf,
        },
        "varianten": varianten,
        "pruefzeit": pruefzeit,
    }


VERLAENGERT = "Lernzeit in die Prüfzeit verlängert"


def _grenze_pruefen(kennung: str, lernzeit_bis: str, abdruck: str, haupt: dict, heute: date,
                    hinweise: list[str]) -> None:
    """Der erste Rückblick merkt sich das Ende der Lernzeit. Wird es später hinausgeschoben,
    hat die Lernzeit einen Teil der Prüfzeit gesehen: Das gilt als Öffnen und wird festgehalten."""
    pfad = konfig.RUECKBLICK / "pruefzeit.json"
    buch = speicher.lies_json(pfad, {}) or {}
    eintrag = buch.setdefault(kennung, {})
    grenze = eintrag.get("grenze")
    if grenze is None:
        eintrag["grenze"] = str(lernzeit_bis)
    elif _monat(lernzeit_bis) > _monat(grenze):
        eintrag.setdefault("oeffnungen", []).append({
            "am": heute.isoformat(), "fingerabdruck": abdruck, "status": VERLAENGERT,
            "von": grenze, "bis": str(lernzeit_bis), "ergebnis": _kurz(haupt)})
        eintrag["grenze"] = str(lernzeit_bis)
        hinweise.append(f"Die Lernzeit reicht jetzt bis {lernzeit_bis} und damit in die frühere Prüfzeit; "
                        "das ist als Öffnen festgehalten.")
    else:
        return
    speicher.schreibe_json(pfad, buch)


def _pruefzeit(g: Geschichte, r: dict, k: dict, kennung: str, lern_bis: int, letzter: int, abdruck: str,
               oeffnen: bool, preisreihe: list[dict], lern_verlauf: list[dict], heute: date, melde) -> dict:
    pfad = konfig.RUECKBLICK / "pruefzeit.json"
    buch = speicher.lies_json(pfad, {}) or {}
    frueher = (buch.get(kennung) or {}).get("oeffnungen") or []
    if not oeffnen:
        return {"status": "verschlossen", "oeffnungen": frueher}
    # Nur so weit, wie Preise vorliegen: sonst rechnete die Zeitmaschine still mit alten Preisen.
    verzug = k["schwellen"]["rueckblick"]["verzug"]
    ende = min(letzter, bilanz.monats_index(preisreihe[-1]["datum"]) + verzug["preis_monate"])
    if ende < letzter:
        g.hinweise.append(f"Preise reichen nur bis {preisreihe[-1]['datum'][:7]}; die Prüfzeit endet deshalb "
                          f"{bilanz.monat_text(ende)}. Vorher den Workflow „Geschichte“ mit „preise“ starten.")
    if ende <= lern_bis:
        return {"status": "noch leer", "oeffnungen": frueher}
    von_t, bis_t = bilanz.monat_text(lern_bis + 1), bilanz.monat_text(ende)
    melde(f"Prüfzeit {von_t} bis {bis_t} wird geöffnet …")
    verlauf = zeitmaschine(g, r, k, lern_bis + 1, ende)
    b = bilanz.bilanz(lern_verlauf + verlauf, preisreihe, von_t, bis_t, k["schwellen"]["rueckblick"],
                      ereignisse=hoehepunkte(g, k, ende), ereignis_fenster=(-3, r["vorlauf_T_monate"]))
    echte = [o for o in frueher if o.get("status") != VERLAENGERT]
    if any(o.get("status") == VERLAENGERT for o in frueher):
        status, unabhaengig = "geöffnet, nachdem die Lernzeit in sie verlängert wurde", False
    elif not echte:
        status, unabhaengig = "erstmals geöffnet", True
    elif echte[0]["fingerabdruck"] == abdruck:
        status, unabhaengig = "erneut geöffnet, Regeln unverändert", True
    else:
        status, unabhaengig = "erneut geöffnet, Regeln oder Datengrundlage inzwischen geändert", False
    frueher.append({"am": heute.isoformat(), "fingerabdruck": abdruck, "status": status,
                    "von": von_t, "bis": bis_t, "ergebnis": _kurz(b)})
    buch.setdefault(kennung, {})["oeffnungen"] = frueher
    speicher.schreibe_json(pfad, buch)
    return {"status": status, "unabhaengig": unabhaengig, "bilanz": b, "verlauf": verlauf, "oeffnungen": frueher}


# ------------------------------------------------------------------ Lauf
def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Rückblick: die Ampel über die Geschichte laufen lassen")
    teiler.add_argument("--rohstoff", default="palmoel")
    teiler.add_argument("--pruefzeit-oeffnen", action="store_true",
                        help="Prüfzeit öffnen (erst, wenn die Regeln feststehen; jedes Öffnen wird festgehalten)")
    teiler.add_argument("--ohne-varianten", action="store_true")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    args = teiler.parse_args(argv)
    k = konfig.konfiguration()
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    try:
        ergebnis = rueckblick(k, args.rohstoff, zeitpunkt, args.pruefzeit_oeffnen, not args.ohne_varianten)
    except Fehlt as grund:
        text = f"## Rückblick {args.rohstoff}\n\nNicht möglich: {grund}\n"
        print(text)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(text)
        return 1
    speicher.schreibe_json(konfig.RUECKBLICK / f"{args.rohstoff}.json", ergebnis)
    rueckblick_text.schreibe(ergebnis, konfig.ABGABE)
    text = rueckblick_text.zusammenfassung(ergebnis)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
