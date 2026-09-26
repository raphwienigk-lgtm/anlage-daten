"""Wächter 3 · Kipppunkt-Register: langsame Messreihen, einmal im Quartal ein Bericht.

Das Register handelt nicht und schaltet keine Ampel. Es zeigt, ob sich Grundannahmen
über eine Anbauregion verschieben; bewertet wird gemeinsam im Quartal. Jede Region hat
ihren dominanten Kipppunkt (konfig/kipppunkte.yaml):

- Kaltfleck südlich von Grönland: Meerestemperatur im subpolaren Atlantik minus
  Weltmittel (ERSSTv5 über NOAA ERDDAP, Weltmittel NOAA Climate at a Glance), dazu die
  Trägheit (Autokorrelation) und Schwankung als Frühzeichen eines Kipppunkts
- RAPID-Messkette bei 26,5 Grad Nord (Met Office Climate Dashboard)
- Häufung starker El Niños (aus dem ONI, den der Tageslauf ohnehin holt)
- Schnee in der Sierra Nevada am 1. April (NRCS SNOTEL)
- Brandherde im Amazonasgebiet (INPE Queimadas, Referenzsatellit)
- Punkte mit Temperatur- und Regenreihen aus ERA5 (Open-Meteo): Mittelmeer,
  Arabica-Gürtel, Kältebedarf von Haselnuss und Mandel

Die Reihen werden fortsetzbar unter daten/kipppunkte/ gesammelt. Der Workflow läuft
täglich; er tut nichts, solange alles da ist und der Bericht für das Quartal steht.

Schreibt daten/kipppunkte.json, abgabe/kipppunkte-teil-N.md, abgabe/status-kipppunkte.md.
Aufruf: python -m anlage.kipppunkte [--erzwingen] [--heute JJJJ-MM-TT] [--budget-minuten 40]
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import math
import time
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from statistics import mean
from urllib.parse import quote

from . import __version__, konfig, netz, speicher
from .module import enso
from .quellen import klimaindizes, openmeteo

MAX_VERSUCHE = 5
HINWEIS = "Denkhilfe, keine Anlageberatung. Messwerte ohne Bewertung; bewertet wird gemeinsam im Quartal."

ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/nceiErsstv5.csv"
CAAG = ("https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series/"
        "globe/ocean/tavg/1/0/1850-{jahr}/data.csv")
AMOC_CSV = "https://climate.metoffice.cloud/formatted_data/amoc_rapid_RAPID.csv"
AMOC_NC = "https://rapid.ac.uk/sites/default/files/rapid_data/moc_transports.nc"
NRCS = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
QUEIMADAS = ("https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_sat_ref/"
             "focos_br_ref_{jahr}.zip")


def ordner():
    return konfig.DATEN / "kipppunkte"


def lade_konfig() -> dict:
    return konfig.lade_yaml(konfig.KONFIG / "kipppunkte.yaml")


# ------------------------------------------------------------------ Statistik
def steigung(xs: list[float], ys: list[float]) -> float | None:
    """Steigung der Ausgleichsgeraden (kleinste Quadrate)."""
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    nenner = sum((x - mx) ** 2 for x in xs)
    if nenner == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / nenner


def rest_nach_trend(xs: list[float], ys: list[float]) -> list[float]:
    b = steigung(xs, ys) or 0.0
    mx, my = mean(xs), mean(ys)
    return [y - (my + b * (x - mx)) for x, y in zip(xs, ys)]


def ac1(werte: list[float]) -> float | None:
    """Autokorrelation mit Verzögerung eins: nahe eins heißt träge."""
    if len(werte) < 5:
        return None
    m = mean(werte)
    nenner = sum((w - m) ** 2 for w in werte)
    if nenner == 0:
        return None
    return sum((a - m) * (b - m) for a, b in zip(werte, werte[1:])) / nenner


def varianz(werte: list[float]) -> float | None:
    if len(werte) < 2:
        return None
    m = mean(werte)
    return sum((w - m) ** 2 for w in werte) / (len(werte) - 1)


def traegheit(jahre: dict[int, float], von: int, bis: int) -> dict | None:
    """Trägheit und Schwankung einer Jahresreihe nach Abzug des Trends (Frühzeichen eines Kipppunkts)."""
    xs = [j for j in range(von, bis + 1) if j in jahre]
    if len(xs) < 20:
        return None
    rest = rest_nach_trend([float(x) for x in xs], [jahre[x] for x in xs])
    return {"von": von, "bis": bis, "n": len(xs), "ac1": _r(ac1(rest), 3), "varianz": _r(varianz(rest), 4)}


def _r(x, stellen=2):
    return None if x is None else round(x, stellen)


def jahresmittel(monate: dict[str, float], mindest: int = 10) -> dict[int, float]:
    gruppen: dict[int, list[float]] = {}
    for m, w in monate.items():
        gruppen.setdefault(int(m[:4]), []).append(w)
    return {j: mean(w) for j, w in gruppen.items() if len(w) >= mindest}


def trend_je_jahrzehnt(jahre: dict[int, float], von: int, bis: int) -> float | None:
    xs = [j for j in range(von, bis + 1) if j in jahre]
    if len(xs) < 10:
        return None
    b = steigung([float(x) for x in xs], [jahre[x] for x in xs])
    return None if b is None else b * 10


def _mittel(jahre: dict[int, float], von: int, bis: int) -> float | None:
    werte = [jahre[j] for j in range(von, bis + 1) if j in jahre]
    return mean(werte) if werte else None


def _letztes_volles_jahr(jahre: dict[int, float], heute: date) -> int | None:
    kandidaten = [j for j in jahre if j < heute.year]
    return max(kandidaten) if kandidaten else None


# ------------------------------------------------------------------ Quellen: lesen
def erddap_url(von: str, bis: str, box: dict) -> str:
    (lat0, lat1), (lon0, lon1) = box["lat"], box["lon"]
    abfrage = f"ssta[({von}):1:({bis})][(0.0)][({lat0}):1:({lat1})][({lon0}):1:({lon1})]"
    return ERDDAP + "?" + quote(abfrage, safe=":(),.-")


def lies_erddap(text: str) -> dict[str, float]:
    """ERDDAP-CSV (time, depth, latitude, longitude, ssta) → flächengewichtetes Monatsmittel."""
    zeilen = list(csv.reader(io.StringIO(text)))
    if not zeilen or "time" not in zeilen[0]:
        raise ValueError("ERDDAP: keine Kopfzeile mit time")
    kopf = zeilen[0]
    i_t, i_lat = kopf.index("time"), kopf.index("latitude")
    i_w = next((i for i, n in enumerate(kopf) if n in ("ssta", "sst")), None)
    if i_w is None:
        raise ValueError("ERDDAP: keine Spalte ssta")
    summen: dict[str, list[float]] = {}
    for z in zeilen[1:]:
        if len(z) <= i_w or z[i_t] in ("UTC", "") or z[i_w] in ("NaN", "", "degree_C"):
            continue
        try:
            wert, lat = float(z[i_w]), float(z[i_lat])
        except ValueError:
            continue
        g = math.cos(math.radians(lat))
        s = summen.setdefault(z[i_t][:7], [0.0, 0.0])
        s[0] += g * wert
        s[1] += g
    if not summen:
        raise ValueError("ERDDAP: keine Werte")
    return {m: s[0] / s[1] for m, s in sorted(summen.items()) if s[1] > 0}


def lies_caag(text: str) -> dict[str, float]:
    """NOAA Climate at a Glance: Zeilen 'JJJJMM,Wert' nach Kommentaren und Kopfzeile."""
    werte = {}
    for zeile in text.splitlines():
        teile = zeile.strip().split(",")
        if len(teile) < 2 or not teile[0].isdigit() or len(teile[0]) != 6:
            continue
        try:
            werte[f"{teile[0][:4]}-{teile[0][4:]}"] = float(teile[1])
        except ValueError:
            continue
    if not werte:
        raise ValueError("Climate at a Glance: keine Werte")
    return werte


def lies_amoc(text: str) -> dict[str, float]:
    zeilen = [z for z in text.splitlines() if z.strip() and not z.lstrip().startswith("#")]
    leser = csv.DictReader(io.StringIO("\n".join(zeilen)))
    spalte = next((f for f in (leser.fieldnames or []) if "Sv" in f and "uncert" not in f.lower()), None)
    if not spalte:
        raise ValueError("AMOC-CSV: keine Spalte in Sv")
    werte = {}
    for z in leser:
        try:
            werte[f"{int(z['Year']):04d}-{int(z['Month']):02d}"] = float(z[spalte])
        except (KeyError, TypeError, ValueError):
            continue
    if not werte:
        raise ValueError("AMOC-CSV: keine Werte")
    return dict(sorted(werte.items()))


def lies_rapid_nc(inhalt: bytes) -> dict[str, float]:
    """RAPID moc_transports.nc (zweimal täglich, Tage seit 1. April 2004) → Monatsmittel der Umwälzung."""
    import netCDF4  # nur im Workflow installiert
    import numpy as np

    with netCDF4.Dataset("moc_transports.nc", memory=inhalt) as nc:
        zeit = nc.variables["time"]
        einheit = zeit.units.replace("since ", "").split()
        basis = date.fromisoformat("-".join(f"{int(t):02d}" for t in einheit[1].split("-")))
        werte = np.ma.filled(np.ma.asarray(nc.variables["moc_mar_hc10"][:], dtype=float), np.nan).tolist()
        tage = np.asarray(zeit[:], dtype=float).tolist()
    summen: dict[str, list[float]] = {}
    for t, w in zip(tage, werte):
        if w is None or math.isnan(w) or w < -9000:
            continue
        tag = basis + timedelta(days=float(t))
        s = summen.setdefault(f"{tag.year:04d}-{tag.month:02d}", [0.0, 0])
        s[0] += float(w)
        s[1] += 1
    # Monate mit wenigstens zwanzig Messtagen (vierzig Werten)
    return {m: round(s[0] / s[1], 2) for m, s in sorted(summen.items()) if s[1] >= 40}


def lies_nrcs(antwort) -> dict:
    """Summe der Schneewasserwerte und der Mediane über alle Stationen mit beidem."""
    summe, median, n = 0.0, 0.0, 0
    for station in antwort or []:
        for element in station.get("data") or []:
            for v in element.get("values") or []:
                w, m = v.get("value"), v.get("median")
                if w is None or m in (None, 0):
                    continue
                summe += float(w)
                median += float(m)
                n += 1
    return {"summe": summe, "median": median, "n": n}


def _einfach(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip().lower()


def zaehle_braende(inhalt: bytes, bioma: str) -> int:
    ziel = _einfach(bioma)
    with zipfile.ZipFile(io.BytesIO(inhalt)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as f:
            leser = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
            if "bioma" not in (leser.fieldnames or []):
                raise ValueError("Queimadas: keine Spalte bioma")
            return sum(1 for z_ in leser if _einfach(z_.get("bioma") or "") == ziel)


# ------------------------------------------------------------------ Indikatoren
def _stuecke(von: date, bis: date, jahre: int = 25) -> list[tuple[date, date]]:
    liste, a = [], von
    while a <= bis:
        e = min(date(a.year + jahre - 1, 12, 31), bis)
        liste.append((a, e))
        a = e + timedelta(days=1)
    return liste


def kaltfleck(k: dict, heute: date) -> dict:
    c = k["kaltfleck"]
    pfad = ordner() / "kaltfleck_box.json"
    box = speicher.lies_json(pfad, {}) or {}
    if box:
        letzter = date.fromisoformat(max(box) + "-01")
        start = date(letzter.year - (1 if letzter.month <= 3 else 0), (letzter.month - 4) % 12 + 1, 1)
    else:
        start = date(c["ab_jahr"], 1, 1)
    stuecke = _stuecke(start, heute)
    for nr, (von, bis) in enumerate(stuecke):
        # Das letzte Stück endet bei „last“: ERDDAP lehnt ein Ende hinter dem letzten Monatswert ab.
        ende = "last" if nr == len(stuecke) - 1 else bis.isoformat()
        box.update(lies_erddap(netz.hole_text(erddap_url(von.isoformat(), ende, c["box"]))))
    speicher.schreibe_json(pfad, dict(sorted(box.items())), kompakt=True)
    welt = lies_caag(netz.hole_text(CAAG.format(jahr=heute.year)))
    schere = jahresmittel({m: w - welt[m] for m, w in box.items() if m in welt})
    allein = jahresmittel(box)
    ref = k["referenz"]
    r_schere, r_allein = _mittel(schere, ref["von"], ref["bis"]), _mittel(allein, ref["von"], ref["bis"])
    if r_schere is None:
        raise ValueError("Kaltfleck: keine Werte in der Vergleichszeit")
    schere = {j: w - r_schere for j, w in schere.items()}
    allein = {j: w - r_allein for j, w in allein.items()}
    ende = _letztes_volles_jahr(schere, heute)
    f = k["fenster_jahre"]
    return {
        "name": c["name"], "kipppunkt": c["kipppunkt"], "region": c["region"], "status": "ok",
        "letzter_monat": max(box), "bis_jahr": ende,
        "schere_letzte_5": _r(_mittel(schere, ende - 4, ende), 2),
        "meer_letzte_5": _r(_mittel(allein, ende - 4, ende), 2),
        "trend_30": _r(trend_je_jahrzehnt(schere, ende - f + 1, ende), 3),
        "traegheit_frueher": traegheit(schere, ende - 2 * f + 1, ende - f),
        "traegheit_jetzt": traegheit(schere, ende - f + 1, ende),
        "jahre": {str(j): _r(w, 3) for j, w in sorted(schere.items())},
    }


def amoc(k: dict, heute: date) -> dict:
    c = k["amoc"]
    werte, quelle = {}, "Met Office"
    try:
        werte = lies_rapid_nc(netz.hole_bytes(AMOC_NC, timeout=120))
        quelle = "RAPID"
    except Exception:  # ohne netCDF4 oder bei Formatwechsel: die Monatsreihe des Met Office
        werte = {}
    if not werte:
        werte, quelle = lies_amoc(netz.hole_text(AMOC_CSV)), "Met Office"
    monate = list(werte)
    liste = list(werte.values())
    xs = [int(m[:4]) + (int(m[5:]) - 0.5) / 12 for m in monate]
    b = steigung(xs, liste)
    return {"name": c["name"], "kipppunkt": c["kipppunkt"], "region": c["region"], "status": "ok",
            "erster_monat": monate[0], "letzter_monat": monate[-1],
            "anfang_4_jahre": _r(mean(liste[:48]), 1), "letzte_12_monate": _r(mean(liste[-12:]), 1),
            "trend_je_jahrzehnt": _r(None if b is None else b * 10, 2), "werte": len(liste), "quelle": quelle}


def el_nino(k: dict, s_enso: dict, heute: date) -> dict:
    c = k["el_nino"]
    ablage = speicher.lies_json(konfig.KLIMA / "oni.json")
    reihe = (ablage or {}).get("reihe")
    if not reihe:
        q = konfig.lade_yaml(konfig.KONFIG / "quellen.yaml")
        reihe = klimaindizes.hole_oni(q["oni"]["url"])
    episoden = enso.episoden(reihe, s_enso)
    ref = k["referenz"]
    ende = heute.year - 1
    fenster = [(ref["von"], ref["bis"]), (1981, 2010), (ende - k["fenster_jahre"] + 1, ende)]
    zaehlung = []
    for von, bis in fenster:
        drin = [e for e in episoden if von <= e["hoehepunkt"]["jahr"] <= bis]
        zaehlung.append({"von": von, "bis": bis, "episoden": len(drin),
                         "stark": sum(e["hoehepunkt"]["wert"] >= c["stark_ab"] for e in drin),
                         "sehr_stark": sum(e["hoehepunkt"]["wert"] >= c["sehr_stark_ab"] for e in drin)})
    laufend = next((e for e in episoden if e["laeuft"]), None)
    return {"name": c["name"], "kipppunkt": c["kipppunkt"], "region": c["region"], "status": "ok",
            "fenster": zaehlung, "laufend": laufend,
            "staerkste": sorted(({"jahr": e["hoehepunkt"]["jahr"], "wert": e["hoehepunkt"]["wert"]} for e in episoden),
                                key=lambda e: -e["wert"])[:5]}


def sierra_schnee(k: dict, heute: date) -> dict:
    c = k["sierra_schnee"]
    pfad = ordner() / "sierra_schnee.json"
    jahre = speicher.lies_json(pfad, {}) or {}
    bis = heute.year if heute >= date(heute.year, 4, 2) else heute.year - 1
    fehlend = [j for j in range(c["ab_jahr"], bis + 1) if str(j) not in jahre]
    if fehlend:
        stationen = netz.hole_json(f"{NRCS}/stations", {"stationTriplets": c["stationen"], "activeOnly": "true"})
        triplets = ",".join(s["stationTriplet"] for s in stationen)
        for j in fehlend:
            antwort = netz.hole_json(f"{NRCS}/data", {"stationTriplets": triplets, "elements": "WTEQ",
                                                      "duration": "DAILY", "beginDate": f"{j}-04-01",
                                                      "endDate": f"{j}-04-01", "centralTendencyType": "MEDIAN"})
            s = lies_nrcs(antwort)
            if s["n"]:
                jahre[str(j)] = {"anteil": round(s["summe"] / s["median"], 3), "stationen": s["n"]}
        speicher.schreibe_json(pfad, dict(sorted(jahre.items())), kompakt=True)
    werte = {int(j): v["anteil"] for j, v in jahre.items()}
    if not werte:
        raise ValueError("Sierra: keine Werte")
    letzt = max(werte)
    return {"name": c["name"], "kipppunkt": c["kipppunkt"], "region": c["region"], "status": "ok",
            "letztes_jahr": letzt, "letzter_anteil": werte[letzt],
            "mittel_10": _r(_mittel(werte, letzt - 9, letzt), 3),
            "mittel_davor": _r(_mittel(werte, min(werte), letzt - 10), 3),
            "arme_jahre_10": sum(werte[j] < c["schwach_bis"] for j in range(letzt - 9, letzt + 1) if j in werte),
            "arme_jahre_davor": sum(w < c["schwach_bis"] for j, w in werte.items() if j <= letzt - 10),
            "jahre_davor": sum(1 for j in werte if j <= letzt - 10),
            "jahre": {str(j): w for j, w in sorted(werte.items())}}


def amazonas_braende(k: dict, heute: date, budget_ende: float) -> dict:
    c = k["amazonas_braende"]
    pfad = ordner() / "amazonas_braende.json"
    jahre = speicher.lies_json(pfad, {}) or {}
    offen = False
    for j in range(c["ab_jahr"], heute.year):
        if str(j) in jahre:
            continue
        if time.monotonic() > budget_ende:
            offen = True
            break
        jahre[str(j)] = zaehle_braende(netz.hole_bytes(QUEIMADAS.format(jahr=j), timeout=300), c["bioma"])
        speicher.schreibe_json(pfad, dict(sorted(jahre.items())), kompakt=True)
    werte = {int(j): v for j, v in jahre.items()}
    if not werte:
        raise ValueError("Amazonas: keine Werte")
    letzt = max(werte)
    return {"name": c["name"], "kipppunkt": c["kipppunkt"], "region": c["region"],
            "status": "unvollständig" if offen else "ok",
            "letztes_jahr": letzt, "letzte_zahl": werte[letzt],
            "mittel_vergleich": _r(_mittel(werte, c["ab_jahr"], c["vergleich_bis"]), 0),
            "vergleich": [c["ab_jahr"], c["vergleich_bis"]],
            "hinweis": "Referenzsatellit; beim Wechsel des Satelliten kann die Reihe springen.",
            "jahre": {str(j): w for j, w in sorted(werte.items())}}


# ------------------------------------------------------------------ Punkte (ERA5)
VARIABLEN = "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum"


def monatswerte(taeglich: dict, heiss_ab: float, kalt_bis: float) -> dict[str, dict]:
    """Tageswerte von Open-Meteo zu Monatswerten: Regen, mittleres Maximum und Mittel, heiße und kalte Tage."""
    zeit = taeglich.get("time") or []
    tmax, tmin = taeglich.get("temperature_2m_max") or [], taeglich.get("temperature_2m_min") or []
    tmit, regen = taeglich.get("temperature_2m_mean") or [], taeglich.get("precipitation_sum") or []
    monate: dict[str, dict] = {}
    for i, t in enumerate(zeit):
        werte = [tmax[i] if i < len(tmax) else None, tmin[i] if i < len(tmin) else None,
                 tmit[i] if i < len(tmit) else None, regen[i] if i < len(regen) else None]
        if any(w is None for w in werte):
            continue
        hoch, tief, mittel, r = werte
        m = monate.setdefault(t[:7], {"tage": 0, "regen": 0.0, "tmax": 0.0, "tmittel": 0.0, "heiss": 0, "kalt": 0})
        m["tage"] += 1
        m["regen"] += r
        m["tmax"] += hoch
        m["tmittel"] += mittel
        m["heiss"] += hoch >= heiss_ab
        m["kalt"] += mittel <= kalt_bis
    for m, w in monate.items():
        w["tmax"] = round(w["tmax"] / w["tage"], 2)
        w["tmittel"] = round(w["tmittel"] / w["tage"], 2)
        w["regen"] = round(w["regen"], 1)
    return monate


def _voll(monate: dict, jahr: int, monat: int) -> dict | None:
    w = monate.get(f"{jahr:04d}-{monat:02d}")
    return w if w and w["tage"] == calendar.monthrange(jahr, monat)[1] else None


def masse(monate: dict) -> dict[str, dict[int, float]]:
    jahre = sorted({int(m[:4]) for m in monate})
    ergebnis: dict[str, dict[int, float]] = {n: {} for n in
                                             ("jahresregen", "sommer_tmax", "jahres_tmittel", "heisse_tage", "kaeltetage")}
    for j in jahre:
        hydro = [_voll(monate, j - 1, m) for m in (10, 11, 12)] + [_voll(monate, j, m) for m in range(1, 10)]
        if all(hydro):
            ergebnis["jahresregen"][j] = round(sum(w["regen"] for w in hydro), 1)
        sommer = [_voll(monate, j, m) for m in (6, 7, 8)]
        if all(sommer):
            ergebnis["sommer_tmax"][j] = round(mean(w["tmax"] for w in sommer), 2)
        jahr = [_voll(monate, j, m) for m in range(1, 13)]
        if all(jahr):
            ergebnis["jahres_tmittel"][j] = round(mean(w["tmittel"] for w in jahr), 2)
            ergebnis["heisse_tage"][j] = sum(w["heiss"] for w in jahr)
        winter = [_voll(monate, j - 1, 11), _voll(monate, j - 1, 12), _voll(monate, j, 1), _voll(monate, j, 2)]
        if all(winter):
            ergebnis["kaeltetage"][j] = sum(w["kalt"] for w in winter)
    return ergebnis


def punkte(k: dict, heute: date, budget_ende: float, pro_minute: float, url: str, modell: str | None) -> dict:
    c = k["punkte"]
    ergebnis, offen = {}, False
    letzter_tag = heute - timedelta(days=8)                    # ERA5 liegt etwa sechs Tage zurück
    for p in c["liste"]:
        pfad = ordner() / f"punkt_{p['kennung']}.json"
        monate = speicher.lies_json(pfad, {}) or {}
        for j in range(c["ab_jahr"], letzter_tag.year + 1):
            start, ende = date(j, 1, 1), min(date(j, 12, 31), letzter_tag)
            fertig = all(_voll(monate, j, m) for m in range(1, ende.month + 1)) if j < letzter_tag.year else False
            if fertig:
                continue
            gew = openmeteo.gewicht((ende - start).days + 1, 4)
            if time.monotonic() + 60.0 * gew / max(pro_minute, 1e-9) > budget_ende and pro_minute > 0:
                offen = True
                break
            antwort = openmeteo._hole(url, openmeteo._parameter(p, start, ende, modell, daily=VARIABLEN))
            if not isinstance(antwort, dict) or antwort.get("error"):
                raise ValueError(f"Open-Meteo {p['name']}: {antwort.get('reason') if isinstance(antwort, dict) else antwort}")
            monate.update(monatswerte(antwort.get("daily") or {}, c["heiss_ab"], c["kalt_bis"]))
            speicher.schreibe_json(pfad, dict(sorted(monate.items())), kompakt=True)
            openmeteo.drossel(gew, pro_minute)
        alle = masse(monate)
        befunde = {}
        for mass in p["masse"]:
            reihe = alle[mass]
            if not reihe:
                continue
            letzt = max(reihe)
            anfang = min(reihe)
            befunde[mass] = {"letztes_jahr": letzt, "letzter_wert": reihe[letzt],
                             "mittel_anfang": _r(_mittel(reihe, anfang, anfang + 29), 2), "anfang": [anfang, anfang + 29],
                             "mittel_10": _r(_mittel(reihe, letzt - 9, letzt), 2),
                             "trend_30": _r(trend_je_jahrzehnt(reihe, letzt - 29, letzt), 3)}
        ergebnis[p["kennung"]] = {"name": p["name"], "kipppunkt": p["kipppunkt"], "region": p["region"],
                                  "masse": befunde, "monate": len(monate), "vollstaendig": not offen,
                                  "bis": max(monate) if monate else None}
        if offen:
            break
    return {"status": "unvollständig" if offen else "ok", "punkte": ergebnis}


# ------------------------------------------------------------------ Gesamt
def quartal(tag: date) -> str:
    return f"{tag.year}-Q{(tag.month - 1) // 3 + 1}"


def rechne(k: dict, s_enso: dict, q: dict, heute: date, budget_ende: float, pro_minute: float) -> dict:
    om = q["openmeteo"]
    aufgaben = {
        "kaltfleck": lambda: kaltfleck(k, heute),
        "amoc": lambda: amoc(k, heute),
        "el_nino": lambda: el_nino(k, s_enso, heute),
        "sierra_schnee": lambda: sierra_schnee(k, heute),
        "amazonas_braende": lambda: amazonas_braende(k, heute, budget_ende),
        "punkte": lambda: punkte(k, heute, budget_ende, pro_minute, om["url"], om.get("modell")),
    }
    ergebnisse = {}
    for name, aufgabe in aufgaben.items():
        try:
            ergebnisse[name] = aufgabe()
        except Exception as fehler:  # ein Indikator darf die anderen nicht mitreißen
            ergebnisse[name] = {"status": "Fehler", "meldung": f"{type(fehler).__name__}: {fehler}"[:300]}
    return ergebnisse


def main(argv: list[str] | None = None) -> int:
    from .ausgabe import kipppunkte_text

    teiler = argparse.ArgumentParser(description="Wächter 3 · Kipppunkt-Register")
    teiler.add_argument("--erzwingen", action="store_true", help="Bericht auch außerhalb des Quartalsbeginns")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (nur Tests)")
    teiler.add_argument("--budget-minuten", type=float, default=40.0)
    teiler.add_argument("--pro-minute", type=float, help="gewichtete Open-Meteo-Abrufe je Minute (0 = ohne Drossel)")
    args = teiler.parse_args(argv)
    zeitpunkt = konfig.jetzt()
    if args.heute:
        zeitpunkt = datetime.combine(date.fromisoformat(args.heute), zeitpunkt.timetz())
    heute = zeitpunkt.date()
    k = lade_konfig()
    alles = konfig.konfiguration()
    q = alles["quellen"]
    pro_minute = args.pro_minute if args.pro_minute is not None else q["openmeteo"].get("gewicht_pro_minute", 75)
    lauf_pfad = ordner() / "lauf.json"
    stand = speicher.lies_json(lauf_pfad, {}) or {}
    faellig = args.erzwingen or stand.get("quartal") != quartal(heute)
    if not faellig and not stand.get("offen"):
        print("Kipppunkt-Register: Bericht für dieses Quartal steht, alle Reihen sind da. Nichts zu tun.")
        return 0
    budget_ende = time.monotonic() + 60.0 * args.budget_minuten
    ergebnisse = rechne(k, alles["schwellen"]["enso"], q, heute, budget_ende, pro_minute)
    offen = any(e.get("status") in ("Fehler", "unvollständig") for e in ergebnisse.values())
    bericht = {"stand": zeitpunkt.isoformat(timespec="seconds"), "datum": heute.isoformat(), "quartal": quartal(heute),
               "version": __version__, "hinweis": HINWEIS, "vollstaendig": not offen, "indikatoren": ergebnisse}
    speicher.schreibe_json(konfig.DATEN / "kipppunkte.json", bericht)
    kipppunkte_text.schreibe(bericht, konfig.ABGABE, k)
    # Fehlt nur noch ein Teil wegen des Zeitbudgets, geht es am nächsten Tag weiter. Scheitert eine
    # Quelle, wird es höchstens an MAX_VERSUCHE Tagen im Quartal erneut versucht.
    versuche = (stand.get("versuche", 0) + 1) if stand.get("versuche_quartal") == quartal(heute) else 1
    budget_offen = any(e.get("status") == "unvollständig" for e in ergebnisse.values())
    weiter = budget_offen or (offen and versuche < MAX_VERSUCHE)
    stand.update({"quartal": quartal(heute), "offen": weiter, "versuche": versuche,
                  "versuche_quartal": quartal(heute),
                  "letzter_lauf": zeitpunkt.isoformat(timespec="seconds"),
                  "status": {n: e.get("status") for n, e in ergebnisse.items()}})
    speicher.schreibe_json(lauf_pfad, stand)
    print(kipppunkte_text.zusammenfassung(bericht))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
