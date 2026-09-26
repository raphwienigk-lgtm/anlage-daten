"""Täglicher Lauf des Anlage-Beobachters (Wächter Klima und Bewerter-Rechnung).

Holt die Daten, rechnet Kaskade, Zeugen, Checkliste, Score und Ampel und schreibt:
- daten/stand.json          alles in Zahlen, für den Cloud-Bewerter
- daten/signale.jsonl       Logbuch der Farbwechsel
- abgabe/anlage-teil-N.md   Vorlesetext, Rohfassung aus den Zahlen
- abgabe/status-anlage.md   fünf Zeilen Status

Eine Quelle, die ausfällt, bricht den Lauf nicht ab. Sie wird im Stand vermerkt.

Aufruf: python -m anlage.lauf [--heute JJJJ-MM-TT] [--ohne-drossel]
"""
from __future__ import annotations

import argparse
import calendar
import os
import time
from datetime import date, datetime, timedelta
from statistics import mean

from . import __version__, kalender, klimatologie, konfig, logbuch, netz, speicher
from .ausgabe import vorlesen
from .module import dipol, enso, regenzeugen
from .netz import AbrufFehler
from .quellen import klimaindizes, kurse, openmeteo
from .rechnen import bewerten

HINWEIS = "Denkhilfe, keine Anlageberatung. Score und Schwellen sind vorläufig, bis das Backtesting steht."


class Quellenbuch:
    """Merkt sich für jede Quelle, ob sie heute geliefert hat."""

    def __init__(self):
        self.eintraege: dict[str, dict] = {}

    def ok(self, schluessel: str, name: str, stand: str | None = None, meldung: str | None = None):
        self.eintraege[schluessel] = {"name": name, "status": "ok", "stand": stand, "meldung": meldung}

    def fehler(self, schluessel: str, name: str, meldung: str, stand: str | None = None):
        self.eintraege[schluessel] = {"name": name, "status": "Fehler", "stand": stand, "meldung": meldung}

    def versuche(self, schluessel: str, name: str, aufgabe, stand_von=None):
        try:
            ergebnis = aufgabe()
        except Exception as fehler:  # Formatänderungen der Quellen dürfen den Lauf nicht stoppen
            art = "" if isinstance(fehler, AbrufFehler) else f"{type(fehler).__name__}: "
            self.fehler(schluessel, name, f"{art}{fehler}")
            return None
        self.ok(schluessel, name, stand_von(ergebnis) if stand_von else None)
        return ergebnis


# ------------------------------------------------------------------ El Niño und Dipol
def _monatsindex(jahr: int, monat: int) -> int:
    return jahr * 12 + monat


def hole_oni(q: dict, heute: date, buch: Quellenbuch, hinweise: list[str]) -> list[dict] | None:
    """ONI mit Ablage: Fällt die Quelle aus, gilt der gespeicherte Stand (und die Ampel kippt nicht)."""
    pfad = konfig.KLIMA / "oni.json"
    name = q["oni"]["name"]
    try:
        reihe = klimaindizes.hole_oni(q["oni"]["url"])
        speicher.schreibe_json(pfad, {"geholt": heute.isoformat(), "reihe": reihe}, kompakt=True)
        buch.ok("oni", name, stand=f"{reihe[-1]['jahreszeit']} {reihe[-1]['jahr']}")
    except Exception as fehler:
        ablage = speicher.lies_json(pfad)
        reihe = (ablage or {}).get("reihe")
        buch.fehler("oni", name, f"{fehler}" + ("; es gilt der gespeicherte Stand" if reihe else ""),
                    stand=f"{reihe[-1]['jahreszeit']} {reihe[-1]['jahr']}" if reihe else None)
    if reihe and _monatsindex(heute.year, heute.month) - _monatsindex(reihe[-1]["jahr"], reihe[-1]["monat"]) > 3:
        hinweise.append(f"El-Niño-Index steht noch auf {reihe[-1]['jahreszeit']} {reihe[-1]['jahr']}, "
                        "das ist älter als üblich.")
    return reihe


def hole_dmi(q: dict, heute: date, buch: Quellenbuch, hinweise: list[str]) -> tuple[list[dict] | None, str | None]:
    """Dipol-Index. Die zuletzt benutzte Quelle wird zuerst gefragt, damit nicht zwischen
    zwei Datensätzen hin- und hergesprungen wird. Fällt sie aus und ist ihr gespeicherter
    Stand höchstens einen Monat älter als die Ersatzquelle, bleibt es beim gespeicherten Stand."""
    pfad = konfig.KLIMA / "dmi.json"
    name = q["dmi"]["name"]
    ablage = speicher.lies_json(pfad) or {}
    quellen = sorted(q["dmi"]["urls"], key=lambda x: x["name"] != ablage.get("quelle"))
    fehler, reihe, quelle = [], None, None
    for eintrag in quellen:
        try:
            reihe, quelle = klimaindizes.lies_monatsreihe(netz.hole_text(eintrag["url"])), eintrag["name"]
            break
        except Exception as f:
            fehler.append(f"{eintrag['name']}: {f}")
    gespeichert = ablage.get("reihe")
    if reihe is None:
        if gespeichert:
            buch.fehler("dmi", name, "; ".join(fehler) + "; es gilt der gespeicherte Stand",
                        stand=f"{gespeichert[-1]['jahr']}-{gespeichert[-1]['monat']:02d} ({ablage['quelle']})")
            return gespeichert, ablage["quelle"]
        buch.fehler("dmi", name, "; ".join(fehler))
        return None, None
    if gespeichert and ablage.get("quelle") != quelle:
        abstand = (_monatsindex(reihe[-1]["jahr"], reihe[-1]["monat"])
                   - _monatsindex(gespeichert[-1]["jahr"], gespeichert[-1]["monat"]))
        if abstand <= 1:
            buch.ok("dmi", name, stand=f"{gespeichert[-1]['jahr']}-{gespeichert[-1]['monat']:02d} ({ablage['quelle']})",
                    meldung=f"{ablage['quelle']} heute nicht erreichbar, gespeicherter Stand gilt")
            return gespeichert, ablage["quelle"]
        hinweise.append(f"Dipol-Index: Quelle gewechselt von {ablage['quelle']} zu {quelle}.")
    speicher.schreibe_json(pfad, {"geholt": heute.isoformat(), "quelle": quelle, "reihe": reihe}, kompakt=True)
    buch.ok("dmi", name, stand=f"{reihe[-1]['jahr']}-{reihe[-1]['monat']:02d} ({quelle})",
            meldung=("; ".join(fehler)) if fehler else None)
    if _monatsindex(heute.year, heute.month) - _monatsindex(reihe[-1]["jahr"], reihe[-1]["monat"]) > 3:
        hinweise.append(f"Dipol-Index steht noch auf {reihe[-1]['monat']:02d}/{reihe[-1]['jahr']}, das ist älter als üblich.")
    return reihe, quelle


# ------------------------------------------------------------------ Regen
def regenbedarf_ab(heute: date, episode_ab: date | None, monate_west: list[int]) -> date:
    """Ab wann Regenwerte im Archiv liegen müssen.

    Mindestens 130 Tage (90-Tage-Fenster plus Puffer), dazu die letzte kurze Regenzeit
    Ostafrikas und bei laufender Episode 90 Tage vor ihrem Beginn. Höchstens 1000 Tage.
    """
    kandidaten = [heute - timedelta(days=130)]
    saisonjahr = heute.year if heute.month >= monate_west[0] else heute.year - 1
    kandidaten.append(date(saisonjahr, monate_west[0], 1))
    if episode_ab:
        kandidaten.append(episode_ab - timedelta(days=90))
    return max(min(kandidaten), heute - timedelta(days=1000))


def hole_regen(k: dict, heute: date, bedarf_ab: date, pro_minute: float, buch: Quellenbuch) -> dict:
    om = k["quellen"]["openmeteo"]
    pfad = konfig.KLIMA / "regen_ist.json"
    archiv = speicher.lies_json(pfad, {}) or {}
    archiv.setdefault("punkte", {})
    ende = heute - timedelta(days=2)
    behalten_ab = min(bedarf_ab, heute - timedelta(days=400))
    fehler, geholt, gestoppt = [], 0, False
    for region in ("ost", "west"):
        for punkt in k["regionen"][region]["punkte"]:
            if gestoppt:
                fehler.append(f"{punkt['name']}: nicht versucht (Limit)")
                continue
            vorhanden = archiv["punkte"].get(punkt["name"], {})
            start = speicher.regen_abrufbeginn(vorhanden, bedarf_ab, heute)
            if start > ende:
                continue
            try:
                neu = openmeteo.hole_tage(om["url"], punkt, start, ende, modell=om.get("modell"))
            except Exception as f:  # auch unerwartete Antworten dürfen den Lauf nicht stoppen
                fehler.append(f"{punkt['name']}: {f}")
                gestoppt = "429" in str(f)
                continue
            finally:
                openmeteo.drossel(openmeteo.gewicht((ende - start).days + 1), pro_minute)
            archiv["punkte"][punkt["name"]] = speicher.regen_zusammenfuehren(vorhanden, neu, behalten_ab)
            geholt += 1
    archiv["stand"] = heute.isoformat()
    archiv["modell"] = om.get("modell")
    speicher.schreibe_json(pfad, archiv, kompakt=True)
    name = "Open-Meteo Regen"
    if fehler and not geholt:
        buch.fehler("regen", name, "; ".join(fehler))
    else:
        buch.ok("regen", name, stand=ende.isoformat(),
                meldung=("teilweise: " + "; ".join(fehler)) if fehler else None)
    return {region: {p["name"]: archiv["punkte"].get(p["name"], {}) for p in k["regionen"][region]["punkte"]}
            for region in ("ost", "west")}


# ------------------------------------------------------------------ Wind
def hole_wind(k: dict, heute: date, jahre: list[int], pro_minute: float, buch: Quellenbuch) -> dict[int, dict]:
    """Mittlerer Ost-West-Wind im Mai und Juni je Jahr, als Abweichung vom Normalen."""
    if not jahre:
        return {}
    om = k["quellen"]["openmeteo"]
    monate = k["schwellen"]["dipol"]["wind_monate"]
    punkte = k["regionen"]["wind_sumatra"]["punkte"]
    pfad = konfig.KLIMA / "wind_ist.json"
    cache = speicher.lies_json(pfad, {}) or {}
    cache.setdefault("jahre", {})
    normal = (speicher.lies_json(konfig.KLIMA / "wind.json", {}) or {}).get("punkte", {})
    fehler = []
    for jahr in jahre:
        eintrag = cache["jahre"].get(str(jahr))
        if eintrag and eintrag.get("vollstaendig"):
            continue
        start = date(jahr, monate[0], 1)
        schluss = date(jahr, monate[-1], calendar.monthrange(jahr, monate[-1])[1])
        ende = min(schluss, heute - timedelta(days=2))
        if ende < start:
            continue
        werte, stunden = {}, []
        for punkt in punkte:
            try:
                mittel, n = openmeteo.hole_mittleren_zonalwind(om["url"], punkt, start, ende,
                                                               modell=om.get("modell"))
                werte[punkt["name"]] = round(mittel, 3)
                stunden.append(n)
            except openmeteo.KeineWerte:
                pass                      # ERA5 liegt einige Tage zurück: Anfang Mai normal
            except Exception as f:
                fehler.append(f"{jahr} {punkt['name']}: {f}")
            finally:
                openmeteo.drossel(openmeteo.gewicht((ende - start).days + 1, 2), pro_minute)
        if werte:
            cache["jahre"][str(jahr)] = {
                "punkte": werte, "bis": ende.isoformat(), "tage": min(stunden) // 24,
                "vollstaendig": len(werte) == len(punkte) and heute >= schluss + timedelta(days=10),
            }
    speicher.schreibe_json(pfad, cache)

    ergebnis = {}
    for jahr in jahre:
        eintrag = cache["jahre"].get(str(jahr))
        if not eintrag:
            ergebnis[jahr] = {"fehler": "noch keine Winddaten"}
            continue
        abweichungen = [u - normal[n]["mittel_ms"] for n, u in eintrag["punkte"].items() if n in normal]
        if not abweichungen:
            ergebnis[jahr] = {"fehler": "Wind-Klimatologie fehlt"}
            continue
        ergebnis[jahr] = {"anomalie_ms": round(mean(abweichungen), 2), "tage": eintrag.get("tage", 0),
                          "vollstaendig": eintrag["vollstaendig"], "bis": eintrag["bis"]}
    if fehler:
        buch.fehler("wind", "Open-Meteo Wind", "; ".join(fehler))
    else:
        buch.ok("wind", "Open-Meteo Wind", stand=max((e.get("bis", "") for e in cache["jahre"].values()), default=None))
    return ergebnis


# ------------------------------------------------------------------ Preise
def hole_fred_mit_archiv(url: str, serie: str, buch: Quellenbuch) -> list[dict] | None:
    pfad = konfig.PREISE / f"fred_{serie}.json"
    name = f"FRED {serie}"
    reihe = buch.versuche(f"fred:{serie}", name, lambda: kurse.hole_fred(url, serie),
                          stand_von=lambda r: r[-1]["datum"])
    if reihe:
        speicher.schreibe_json(pfad, reihe, kompakt=True)
        return reihe
    return speicher.lies_json(pfad)


def hole_kurse(tickers: list[str], historie: str, heute: date, buch: Quellenbuch) -> tuple[dict, dict]:
    """Tageskurse je Ticker, ergänzt ins Preisarchiv. Fällt Yahoo aus, gilt das Archiv."""
    reihen, fehler = {}, {}
    for ticker in tickers:
        pfad = kurse.archiv_pfad(konfig.PREISE, ticker)
        try:
            archiv = kurse.lies_archiv(pfad)
        except (ValueError, KeyError) as f:
            print(f"Warnung: Preisarchiv {pfad.name} beschädigt, wird neu aufgebaut ({f})")
            pfad.unlink()
            archiv = []
        genug = len(archiv) >= 250 and archiv[-1]["datum"] >= (heute - timedelta(days=10)).isoformat()
        zeitraum = "1mo" if genug else historie
        try:
            neu = kurse.hole_yahoo(ticker, zeitraum)
        except Exception as f:
            fehler[ticker] = str(f)
            buch.fehler(f"yahoo:{ticker}", f"Yahoo {ticker}", str(f),
                        stand=archiv[-1]["datum"] if archiv else None)
            reihen[ticker] = archiv
            continue
        reihen[ticker] = kurse.ergaenze_archiv(pfad, neu)
        buch.ok(f"yahoo:{ticker}", f"Yahoo {ticker}", stand=reihen[ticker][-1]["datum"])
    return reihen, fehler


# ------------------------------------------------------------------ Lauf
def zustand(buch: Quellenbuch, enso_lage, hinweise: list[str]) -> str:
    if enso_lage is None:
        return "Fehler"
    if any(e["status"] == "Fehler" for e in buch.eintraege.values()) or hinweise:
        return "Warnung"
    return "in Ordnung"


def lauf(heute: date | None = None, pro_minute: float | None = None) -> dict:
    beginn = time.monotonic()
    k = konfig.konfiguration()
    zeitpunkt = konfig.jetzt()
    if heute is None:
        heute = zeitpunkt.date()
    else:
        zeitpunkt = datetime.combine(heute, zeitpunkt.timetz())
    q, s = k["quellen"], k["schwellen"]
    if pro_minute is None:
        pro_minute = q["openmeteo"].get("gewicht_pro_minute", 75)
    buch = Quellenbuch()
    hinweise = []

    rohstoffe = {}
    for kennung, eintrag in k["rohstoffe"].items():
        fehler = konfig.pruefe_rohstoff(eintrag, k["regionen"])
        if fehler:
            hinweise.append(f"Formular {kennung} fehlerhaft: " + "; ".join(fehler))
        elif eintrag.get("rolle") != "verworfen":
            rohstoffe[kennung] = eintrag
    vorlauf = max([r.get("vorlauf_T_monate", 12) for r in rohstoffe.values()] or [12])

    # 1. El Niño und Dipol-Index
    oni = hole_oni(q, heute, buch, hinweise)
    enso_lage = enso.lage(oni, s["enso"], heute, vorlauf) if oni else None
    episode_ab = enso.episode_beginn(enso_lage)
    episode_bis = enso.zaehlt_bis(enso_lage)
    dmi, dmi_quelle = hole_dmi(q, heute, buch, hinweise)

    # 2. Regen und Wind
    bedarf = regenbedarf_ab(heute, episode_ab, s["zeugen"]["west"]["monate"])
    regen = hole_regen(k, heute, bedarf, pro_minute, buch)
    regen_normal = speicher.lies_json(konfig.KLIMA / "regen.json")
    regenpunkte = k["regionen"]["ost"]["punkte"] + k["regionen"]["west"]["punkte"]
    fehlend = [p["name"] for p in regenpunkte if not klimatologie.ist_fertig(regen_normal, p)]
    if len(fehlend) == len(regenpunkte):
        hinweise.append("Regen-Klimatologie fehlt: einmal den Workflow „Klimatologie“ starten.")
    elif fehlend:
        hinweise.append(f"Regen-Klimatologie unvollständig ({len(fehlend)} von {len(regenpunkte)} Punkten fehlen): "
                        "den Workflow „Klimatologie“ noch einmal starten.")
    zeugen = regenzeugen.zeugen(regen["ost"], regen["west"], regen_normal, s["zeugen"], heute,
                                episode_ab, episode_bis)
    wind_monate = s["dipol"]["wind_monate"]
    ep_jahre = enso.episode_jahre(enso_lage, heute)
    wind_jahre_noetig = sorted(set(ep_jahre) | ({heute.year} if heute.month >= wind_monate[0] else set()))
    wind = hole_wind(k, heute, wind_jahre_noetig, pro_minute, buch)
    wind_normal = speicher.lies_json(konfig.KLIMA / "wind.json")
    if wind_jahre_noetig and not all(klimatologie.ist_fertig(wind_normal, p)
                                     for p in k["regionen"]["wind_sumatra"]["punkte"]):
        hinweise.append("Wind-Klimatologie fehlt oder ist unvollständig: den Workflow „Klimatologie“ starten.")
    dipol_lage = dipol.lage(enso_lage, episode_ab, episode_bis, ep_jahre, dmi, dmi_quelle, wind, zeugen,
                            k["handeingaben"], heute, s["dipol"])
    if dipol_lage["prognose"].get("fehler"):
        hinweise.append(dipol_lage["prognose"]["fehler"])

    # 3. Preise und Kurse
    gegen_ticker = q["yahoo"]["gegenkraefte"]
    tickers = sorted({gegen_ticker[g["kennung"]] for r in rohstoffe.values()
                      for g in r.get("gegenkraefte", []) if g["kennung"] in gegen_ticker}
                     | {i["ticker"] for r in rohstoffe.values() for i in r.get("instrumente", [])})
    kursreihen, kursfehler = hole_kurse(tickers, s["kurse"]["historie"], heute, buch)

    # 4. Bewerten
    bewertungen = {}
    for kennung, r in rohstoffe.items():
        try:
            preis = r["preis"]
            preisreihe = (hole_fred_mit_archiv(q["fred"]["url"], preis["serie"], buch)
                          if preis["quelle"] == "fred" else None)
            gegen_reihen = {g["kennung"]: kursreihen.get(gegen_ticker.get(g["kennung"]), [])
                            for g in r.get("gegenkraefte", [])}
            b = bewerten.bewerte(r, enso_lage, dipol_lage if "dipol" in r.get("kopplungen", []) else None,
                                 preisreihe, gegen_reihen, kursreihen, kursfehler, s, k["veto"], heute)
        except Exception as fehler:  # ein Rohstoff mit Fehler darf die anderen nicht mitreißen
            hinweise.append(f"{r['name']}: Bewertung fehlgeschlagen ({type(fehler).__name__}: {fehler})")
            b = {"name": r["name"], "kennung": kennung, "ampel": None, "hinweis": "Bewertung fehlgeschlagen"}
        for text in (b.get("ampel") or {}).get("veto_fehler", []):
            if text not in hinweise:
                hinweise.append(text)
        bewertungen[kennung] = b

    # 5. Logbuch, Stand, Vorlesetext
    neu = logbuch.ergaenze(konfig.DATEN / "signale.jsonl", zeitpunkt.isoformat(timespec="seconds"), bewertungen)
    stand = {
        "stand": zeitpunkt.isoformat(timespec="seconds"),
        "datum": heute.isoformat(),
        "version": __version__,
        "hinweis": HINWEIS,
        "zustand": zustand(buch, enso_lage, hinweise),
        "hinweise": hinweise,
        "quellen": buch.eintraege,
        "klima": {"enso": enso_lage, "dipol": dipol_lage},
        "rohstoffe": bewertungen,
        "kalender": kalender.naechste(k["kalender"], heute),
        "handeingaben": k["handeingaben"],
        "logbuch_neu": neu,
        "laufzeit_sekunden": round(time.monotonic() - beginn, 1),
    }
    speicher.schreibe_json(konfig.DATEN / "stand.json", stand)
    vorlesen.schreibe(stand, konfig.ABGABE)
    return stand


def zusammenfassung(stand: dict) -> str:
    zeilen = [f"## Anlage-Beobachter, {stand['stand']}", "", f"Zustand: **{stand['zustand']}**", ""]
    for b in stand["rohstoffe"].values():
        ampel = b.get("ampel")
        zeilen.append(f"- {b['name']}: {ampel['anzeige'] if ampel else b.get('hinweis')}")
    kaputt = [f"{e['name']}: {e['meldung']}" for e in stand["quellen"].values() if e["status"] == "Fehler"]
    if kaputt or stand["hinweise"]:
        zeilen += ["", "Auffällig:"] + [f"- {t}" for t in kaputt + stand["hinweise"]]
    return "\n".join(zeilen) + "\n"


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Täglicher Lauf des Anlage-Beobachters")
    teiler.add_argument("--heute", help="Stichtag JJJJ-MM-TT (zum Testen)")
    teiler.add_argument("--ohne-drossel", action="store_true", help="Open-Meteo nicht drosseln (nur Tests)")
    args = teiler.parse_args(argv)
    heute = date.fromisoformat(args.heute) if args.heute else None
    stand = lauf(heute, pro_minute=0 if args.ohne_drossel else None)
    text = zusammenfassung(stand)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
