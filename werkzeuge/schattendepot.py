#!/usr/bin/env python3
"""Gesamt-Schattendepot des Rohstoff-Frühwarnsystems (Auftrag 27.09.2026).

Sammelt die gedachten Positionen aller Zweige an einem Ort und bewertet sie mit einem festen, erfundenen
Betrag je Wert (Formular konfig/depot.yaml, 1.000 Euro). Reine Rechnung, kein echtes Geld.

- Palmöl: gedachte Käufe aus dem Logbuch daten/signale.jsonl (Rot kauft jeden Wert des Rohstoffs, Grün schließt).
- Ersatz-Sensoren: daten/ersatz/<kennung>/schattendepot.json.
- Metall: Das Schattendepot führt der Metall-Wächter in der Cloud (metall-logbuch.md); der Depot-Agent übergibt
  es als Zusatzdatei (--zusatz), weil GitHub es nicht kennt.

Jeder gedachte Kauf eines Werts erhält den Betrag, umgerechnet zum Devisenkurs am Kurstag des Kaufs. Bewertet
wird zum letzten Schlusskurs bis heute, bei geschlossenen Positionen zum Schlusskurs am Schlusstag, zurück in
Euro zum Devisenkurs desselben Tages. Dazu der Vergleichsmaßstab des Zweigs im selben Zeitraum und die Frist
nach der geltenden Ausstiegsregel.

Nur Standardbibliothek, damit der Depot-Agent es in der Cloud ohne Installation ausführen kann:

    python3 schattendepot.py dateien --index daten/depot/index.json
    python3 schattendepot.py rechnen --basis . --heute JJJJ-MM-TT [--zusatz metall.json] --aus depot.json

Das Verzeichnis --basis enthält die Dateien aus dem Repository unter ihren Pfaden (daten/…), so wie sie
`dateien` auflistet. Denkhilfe, keine Anlageberatung.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

VERSION = "1.0"
HINWEIS = "Reine Rechnung mit einem erfundenen Betrag, kein echtes Geld. Denkhilfe, keine Anlageberatung."
NEU_TAGE = 7          # so lange gilt ein Kauf oder Schluss als neu
FRIST_BALD = 7        # Hinweis, wenn die Frist in so vielen Tagen erreicht ist
KURS_ALT = 5          # Kalendertage, ab denen der letzte Kurs einer offenen Position als alt gilt


# ------------------------------------------------------------------ Einlesen
def lies_archiv(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    with open(pfad, encoding="utf-8") as f:
        return [{"datum": z["datum"], "schluss": float(z["schluss"])} for z in csv.DictReader(f) if z.get("schluss")]


def lies_jsonl(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    zeilen = []
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            try:
                zeilen.append(json.loads(zeile))
            except json.JSONDecodeError:
                continue
    return zeilen


def lies_json(pfad: Path, ersatz=None):
    """Fehlt die Datei oder ist sie kein JSON (etwa eine gespeicherte 404-Antwort), kommt `ersatz` zurück."""
    if not pfad.exists():
        return ersatz
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ersatz


class Reihe:
    """Schlusskurse eines Werts mit Suche nach Datum."""

    def __init__(self, zeilen: list[dict]):
        self.zeilen = sorted(zeilen, key=lambda z: z["datum"])
        self.daten = [z["datum"] for z in self.zeilen]

    def __bool__(self):
        return bool(self.zeilen)

    def bis(self, tag: str) -> dict | None:
        """Letzter Kurs am oder vor dem Tag."""
        i = bisect_right(self.daten, tag)
        return self.zeilen[i - 1] if i else None

    def ab(self, tag: str) -> dict | None:
        """Erster Kurs am oder nach dem Tag."""
        i = bisect_right(self.daten, tag)
        if i and self.daten[i - 1] == tag:
            return self.zeilen[i - 1]
        return self.zeilen[i] if i < len(self.zeilen) else None

    def um(self, tag: str) -> dict | None:
        """Kurs am oder vor dem Tag, sonst der erste danach (für Devisen vor Beginn des Archivs)."""
        return self.bis(tag) or self.ab(tag)

    def spanne(self, von: str, bis: str) -> list[float]:
        return [z["schluss"] for z in self.zeilen if von <= z["datum"] <= bis]


# ------------------------------------------------------------------ Positionen sammeln
def _tag(zeit: str | None) -> str | None:
    return zeit[:10] if zeit else None


def aus_logbuch(eintraege: list[dict], rohstoff: str, zweig: str) -> list[dict]:
    """Palmöl und andere Agrar-Rohstoffe: Rot kauft jeden Wert des Rohstoffs gedacht, Grün schließt."""
    positionen, offen = [], []
    for e in eintraege:
        if e.get("rohstoff") != rohstoff:
            continue
        if e.get("schattenschluss") and offen:
            for p in offen:
                ende = (e.get("kurse") or {}).get(p["ticker"]) or {}
                p.update({"schluss": _tag(e.get("zeit")), "schlusskurs": ende.get("kurs"),
                          "schlusskurs_datum": ende.get("datum"), "grund": "Rückkehr auf Grün"})
            offen = []
        if e.get("schattenkauf") and not offen:
            for ticker, k in (e.get("kurse") or {}).items():
                p = {"zweig": zweig, "ticker": ticker, "seit": _tag(e.get("zeit")), "kurs": k.get("kurs"),
                     "kurs_datum": k.get("datum"), "anlass": f"Rot, Zahl {e.get('zahl')}" if e.get("zahl") else "Rot"}
                positionen.append(p)
                offen.append(p)
    return positionen


def aus_ersatz(depot: dict, zweig: str) -> list[dict]:
    positionen = []
    for pos in (depot or {}).get("positionen", []):
        for ticker, k in (pos.get("kurse") or {}).items():
            ende = (pos.get("schluss_kurse") or {}).get(ticker) or {}
            ref0 = next(iter((pos.get("vergleich") or {}).values()), None) or {}
            ref1 = next(iter((pos.get("schluss_vergleich") or {}).values()), None) or {}
            positionen.append({
                "zweig": zweig, "ticker": ticker, "seit": _tag(pos.get("zeit")), "kurs": k.get("kurs"),
                "kurs_datum": k.get("datum"), "anlass": pos.get("grund") or "Rot",
                "schluss": _tag(pos.get("schluss_zeit")), "schlusskurs": ende.get("kurs"),
                "schlusskurs_datum": ende.get("datum"), "grund": pos.get("schluss_grund"),
                "vergleich_kurs": ref0.get("kurs"), "vergleich_schluss": ref1.get("kurs"),
            })
    return positionen


def aus_zusatz(liste: list[dict], index: dict) -> tuple[list[dict], list[str]]:
    """Positionen aus der Cloud, etwa das Schattendepot des Metall-Wächters. Pflicht: zweig, ticker, seit."""
    positionen, fehler = [], []
    for p in liste or []:
        if not (p.get("zweig") and p.get("ticker") and p.get("seit")):
            fehler.append(f"Zusatz ohne zweig, ticker oder seit: {json.dumps(p, ensure_ascii=False)[:120]}")
            continue
        if p["ticker"] not in index["werte"]:
            fehler.append(f"Zusatz mit unbekanntem Wert {p['ticker']}")
            continue
        positionen.append({k: p.get(k) for k in ("zweig", "ticker", "seit", "kurs", "kurs_datum", "anlass",
                                                  "schluss", "schlusskurs", "schlusskurs_datum", "grund")})
    return positionen, fehler


# ------------------------------------------------------------------ Frist
def frist(seit: str, regel: dict | None) -> tuple[str | None, str]:
    """Spätester Schluss nach der geltenden Regel; bei Regeln ohne festes Datum None und eine Beschreibung."""
    regel = regel or {}
    tag = date.fromisoformat(seit)
    if regel.get("kalendertage"):
        text = f"nach {regel['kalendertage']} Tagen"
        if regel.get("lockerung"):
            text += " oder früher bei einer Lockerung"
        return (tag + timedelta(days=regel["kalendertage"])).isoformat(), text
    if regel.get("bis_monat_tag"):
        ende = date.fromisoformat(f"{tag.year}-{regel['bis_monat_tag']}")
        if ende < tag:
            ende = date.fromisoformat(f"{tag.year + 1}-{regel['bis_monat_tag']}")
        return ende.isoformat(), "am Ende der Ernte"
    if regel.get("gruen"):
        return None, "wenn die Ampel auf Grün springt"
    return None, "ohne feste Frist"


# ------------------------------------------------------------------ Bewerten
def bewerte(p: dict, index: dict, basis: Path, heute: date, reihen: dict) -> dict:
    wert = index["werte"][p["ticker"]]
    zweig = index["zweige"].get(p["zweig"], {})
    betrag = float(index["betrag"])

    def reihe(pfad: str | None) -> Reihe:
        if not pfad:
            return Reihe([])
        if pfad not in reihen:
            reihen[pfad] = Reihe(lies_archiv(basis / pfad))
        return reihen[pfad]

    kurse = reihe(wert.get("archiv"))
    ergebnis = {"zweig": p["zweig"], "zweig_name": zweig.get("name", p["zweig"]), "ticker": p["ticker"],
                "name": wert.get("name", p["ticker"]), "waehrung": wert.get("waehrung"), "seit": p["seit"],
                "anlass": p.get("anlass"), "offen": not p.get("schluss"), "schluss": p.get("schluss"),
                "grund": p.get("grund"), "einsatz_eur": round(betrag, 2)}
    for feld in ("achse",):
        if wert.get(feld):
            ergebnis[feld] = wert[feld]

    # Einstieg: mitgegebener Kurs, sonst der erste Schlusskurs ab dem Kauftag
    p0, d0 = p.get("kurs"), p.get("kurs_datum") or p["seit"]
    if not p0:
        z = kurse.ab(p["seit"]) if kurse else None
        if not z:
            return {**ergebnis, "status": "ohne Einstiegskurs"}
        p0, d0 = z["schluss"], z["datum"]
    p0 = float(p0)

    # Ende: Schlusskurs der Position, sonst der letzte Kurs bis zum Schlusstag oder bis heute
    stichtag = p.get("schluss") or heute.isoformat()
    if p.get("schluss") and p.get("schlusskurs"):
        p1, d1 = float(p["schlusskurs"]), p.get("schlusskurs_datum") or p["schluss"]
    else:
        z = kurse.bis(stichtag) if kurse else None
        if z and z["datum"] >= d0:
            p1, d1 = z["schluss"], z["datum"]
        else:
            p1, d1 = p0, d0

    # Devisen: Einheiten der Fremdwährung je Euro
    waehrung = wert.get("waehrung") or index.get("basis", "EUR")
    if waehrung == index.get("basis", "EUR"):
        fx0 = fx1 = 1.0
    else:
        devisen = reihe((index.get("devisen") or {}).get(waehrung))
        z0, z1 = devisen.um(d0), devisen.um(d1)
        if not (z0 and z1):
            return {**ergebnis, "status": f"ohne Devisenkurs für {waehrung}"}
        fx0, fx1 = z0["schluss"], z1["schluss"]

    menge = betrag * fx0 / p0
    wert_eur = menge * p1 / fx1
    verlauf = kurse.spanne(d0, d1) if kurse else []
    verlauf = verlauf or [p0, p1]
    ergebnis.update({
        "status": "ok",
        "einstieg": {"kurs": p0, "datum": d0, "devisen": fx0},
        "ende": {"kurs": p1, "datum": d1, "devisen": fx1, "art": "Schluss" if p.get("schluss") else "heute"},
        "menge": round(menge, 6),
        "wert_eur": round(wert_eur, 2),
        "veraenderung_eur": round(wert_eur / betrag - 1, 4),
        "veraenderung_lokal": round(p1 / p0 - 1, 4),
        "hoechster": round(max(verlauf) / p0 - 1, 4),
        "tiefster": round(min(verlauf) / p0 - 1, 4),
        "tage": ((date.fromisoformat(p["schluss"]) if p.get("schluss") else heute) - date.fromisoformat(p["seit"])).days,
        "kurs_alter_tage": (heute - date.fromisoformat(d1)).days if not p.get("schluss") else None,
    })

    # Vergleichsmaßstab im selben Zeitraum, in Landeswährung wie der Wert
    ref_ticker = wert.get("vergleich")
    if ref_ticker:
        ref = index.get("vergleiche", {}).get(ref_ticker, {})
        rr = reihe(ref.get("archiv"))
        v0 = p.get("vergleich_kurs") or ((rr.bis(d0) or {}).get("schluss") if rr else None)
        v1 = p.get("vergleich_schluss") if p.get("schluss") else None
        v1 = v1 or ((rr.bis(d1) or {}).get("schluss") if rr else None)
        if v0 and v1:
            veraenderung = round(v1 / v0 - 1, 4)
            ergebnis["vergleich"] = {"ticker": ref_ticker, "name": ref.get("name", ref_ticker),
                                     "veraenderung": veraenderung,
                                     "vorsprung": round(ergebnis["veraenderung_lokal"] - veraenderung, 4)}

    # Frist nach der geltenden Regel
    regel = zweig.get("regel") or {}
    ende_frist, beschreibung = frist(p["seit"], regel)
    ergebnis["regel"] = {"gilt": zweig.get("gilt", "bisher"), "name": zweig.get("regel_name"), "frist": ende_frist,
                         "beschreibung": beschreibung}
    if ergebnis["offen"] and ende_frist:
        ergebnis["regel"]["tage_bis_frist"] = (date.fromisoformat(ende_frist) - heute).days
    return ergebnis


def _summe(positionen: list[dict]) -> dict:
    ok = [p for p in positionen if p.get("status") == "ok"]
    einsatz = sum(p["einsatz_eur"] for p in ok)
    wert = sum(p["wert_eur"] for p in ok)
    return {"anzahl": len(ok), "einsatz_eur": round(einsatz, 2), "wert_eur": round(wert, 2),
            "veraenderung_eur": round(wert / einsatz - 1, 4) if einsatz else None,
            "ergebnis_eur": round(wert - einsatz, 2)}


def hinweise(positionen: list[dict], index: dict, heute: date) -> list[dict]:
    """Regel-Hinweise: was die geltenden Regeln heute ergeben. Der Depot-Agent formuliert daraus Sätze."""
    liste = []
    neu_ab = (heute - timedelta(days=NEU_TAGE)).isoformat()
    for p in positionen:
        kopf = {"zweig": p["zweig"], "ticker": p["ticker"], "name": p["name"]}
        if p.get("status") != "ok":
            liste.append({**kopf, "art": "nicht_bewertbar", "text": p.get("status")})
            continue
        r = p["regel"]
        if p["offen"]:
            if p["seit"] >= neu_ab:
                liste.append({**kopf, "art": "neu_gekauft", "seit": p["seit"], "anlass": p.get("anlass")})
            if r.get("frist") is not None:
                if r["tage_bis_frist"] <= 0:
                    liste.append({**kopf, "art": "frist_erreicht", "frist": r["frist"], "regel": r["beschreibung"]})
                elif r["tage_bis_frist"] <= FRIST_BALD:
                    liste.append({**kopf, "art": "frist_bald", "frist": r["frist"], "regel": r["beschreibung"],
                                  "tage": r["tage_bis_frist"]})
            if (p.get("kurs_alter_tage") or 0) > KURS_ALT:
                liste.append({**kopf, "art": "kurs_alt", "datum": p["ende"]["datum"]})
        elif p.get("schluss") and p["schluss"] >= neu_ab:
            liste.append({**kopf, "art": "neu_geschlossen", "schluss": p["schluss"], "grund": p.get("grund"),
                          "veraenderung_eur": p["veraenderung_eur"]})
    for kennung, z in index["zweige"].items():
        if z.get("gilt", "bisher") != "bisher":
            liste.append({"zweig": kennung, "art": "regel_abweichend", "gilt": z["gilt"],
                          "text": "Für diesen Zweig gilt eine andere Ausstiegsregel; ihre tägliche Prüfung "
                                  "im Schattendepot ist noch nicht eingebaut."})
    return liste


def rechnen(basis: Path, heute: date, zusatz: list[dict] | None = None) -> dict:
    index = lies_json(basis / "daten" / "depot" / "index.json")
    if not index:
        raise SystemExit("daten/depot/index.json fehlt")
    roh, fehler = [], []
    for kennung, z in index["zweige"].items():
        q = z.get("quelle") or {}
        if q.get("art") == "logbuch":
            roh += aus_logbuch(lies_jsonl(basis / q["pfad"]), q["rohstoff"], kennung)
        elif q.get("art") == "ersatz":
            roh += aus_ersatz(lies_json(basis / q["pfad"], {"positionen": []}), kennung)
    mehr, fehler_zusatz = aus_zusatz(zusatz, index)
    roh += mehr
    fehler += fehler_zusatz
    unbekannt = [p for p in roh if p["ticker"] not in index["werte"]]
    fehler += [f"Wert {p['ticker']} fehlt im Index" for p in unbekannt]
    roh = [p for p in roh if p["ticker"] in index["werte"] and p["zweig"] in index["zweige"]]
    reihen: dict = {}
    positionen = [bewerte(p, index, basis, heute, reihen) for p in roh]
    positionen.sort(key=lambda p: (not p["offen"], p["zweig"], p["seit"], p["ticker"]))
    offen = [p for p in positionen if p["offen"]]
    zu = [p for p in positionen if not p["offen"]]
    zweige = {}
    for kennung, z in index["zweige"].items():
        eigene = [p for p in positionen if p["zweig"] == kennung]
        zweige[kennung] = {"name": z.get("name", kennung), "gilt": z.get("gilt", "bisher"),
                           "regel_name": z.get("regel_name"),
                           "offen": _summe([p for p in eigene if p["offen"]]),
                           "geschlossen": _summe([p for p in eigene if not p["offen"]])}
    return {
        "stand": heute.isoformat(),
        "version": VERSION,
        "hinweis": HINWEIS,
        "betrag_je_wert_eur": float(index["betrag"]),
        "basis": index.get("basis", "EUR"),
        "index_stand": index.get("stand"),
        "gesamt": {"offen": _summe(offen), "geschlossen": _summe(zu), "zusammen": _summe(positionen)},
        "zweige": zweige,
        "positionen": positionen,
        "regel_hinweise": hinweise(positionen, index, heute),
        "fehler": fehler + [f"{p['ticker']}: {p['status']}" for p in positionen if p.get("status") != "ok"],
    }


# ------------------------------------------------------------------ Aufruf
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gesamt-Schattendepot des Rohstoff-Frühwarnsystems")
    unter = parser.add_subparsers(dest="befehl", required=True)
    d = unter.add_parser("dateien", help="Pfade der Dateien, die das Rechnen braucht")
    d.add_argument("--index", default="daten/depot/index.json")
    r = unter.add_parser("rechnen", help="Schattendepot bewerten")
    r.add_argument("--basis", default=".")
    r.add_argument("--heute", help="JJJJ-MM-TT (Europe/Berlin)")
    r.add_argument("--zusatz", help="JSON-Liste weiterer Positionen, etwa aus dem Metall-Logbuch")
    r.add_argument("--aus", help="Ergebnis als JSON in diese Datei, sonst auf die Standardausgabe")
    a = parser.parse_args(argv)
    if a.befehl == "dateien":
        index = lies_json(Path(a.index))
        if not index:
            print(f"{a.index} fehlt", file=sys.stderr)
            return 1
        print("\n".join(index["dateien"]))
        return 0
    heute = date.fromisoformat(a.heute) if a.heute else date.today()
    zusatz = lies_json(Path(a.zusatz), []) if a.zusatz else []
    ergebnis = rechnen(Path(a.basis), heute, zusatz)
    text = json.dumps(ergebnis, ensure_ascii=False, indent=1)
    if a.aus:
        Path(a.aus).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
