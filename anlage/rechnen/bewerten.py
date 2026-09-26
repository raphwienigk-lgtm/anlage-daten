"""Bewerter für Agrar-Werte mit Klima-Treiber (zuerst Palmöl).

Reihenfolge wie im Konzept:
1. Checkliste: Auslöser, Zeitfenster, Gegenkräfte, Preisprobe.
2. Farbe aus Checkliste und Zeitfenster, bei Dipol-Kopplung dazu Kaskade und
   Kreuzbestätigung. Rot heißt: Ereignis bestätigt, Zeitfenster wird knapp,
   der Markt schläft noch.
3. Zahl dahinter aus dem Score, umgerechnet auf 1 bis 10. Seit 26.09.2026 ohne das
   Zeitfenster: Die Farbe sagt, wann es so weit ist, die Zahl, wie gut der Kandidat ist.
   VORLÄUFIG, bis die Gewichte am Backtesting geprüft sind.
4. Politik-Veto als letzte Schicht.

Grundsatz: Formeln hier in Python, Urteile bei Claude. Nichts hier kauft oder verkauft.
"""
from __future__ import annotations

import math
from datetime import date
from statistics import mean

from ..module import enso
from .kennzahlen import begrenze, veraenderung, volumen_trend, zwert

STUFEN = ["Grün", "Gelb", "Rot"]
OHNE_URTEIL = "ohne Urteil"   # Auslöser heute nicht lesbar: keine Farbe, kein Logbuch-Eintrag


def _runde(x: float | None, stellen: int = 3) -> float | None:
    return None if x is None else round(x, stellen)


# ------------------------------------------------------------------ Checkliste
def gegenkraefte(rohstoff: dict, reihen: dict[str, list[dict]], schwellen: dict) -> dict:
    """Punkt 3. Druck je Gegenkraft = Preisrückgang in drei Monaten, 20 % Rückgang = voller Druck."""
    voll = schwellen["gegen_voll_bei"]
    einzeln = {}
    for g in rohstoff.get("gegenkraefte", []):
        reihe = reihen.get(g["kennung"])
        d = veraenderung(reihe, 91) if reihe else None
        einzeln[g["kennung"]] = {
            "text": g.get("text", g["kennung"]),
            "veraenderung_3m": _runde(d),
            "druck": _runde(begrenze(-d / voll)) if d is not None else None,
        }
    druecke = [e["druck"] for e in einzeln.values() if e["druck"] is not None]
    wert = _runde(mean(druecke)) if druecke else None
    return {
        "wert": wert,
        "ueberwiegen": None if wert is None else wert >= schwellen["gegenkraefte_ueberwiegen_ab"],
        "einzeln": einzeln,
        "fehlend": [k for k, e in einzeln.items() if e["druck"] is None],
    }


def preisprobe(rohstoff: dict, reihe: list[dict] | None, schwellen: dict) -> dict:
    """Punkt 4. Z-Wert des Rohstoffpreises selbst (Monatswerte)."""
    fenster = rohstoff["preis"]["z_fenster_monate"]
    if not reihe:
        return {"z": None, "markt_schlaeft": None, "status": "kein Preis", "fenster_monate": fenster}
    z = zwert([e["wert"] for e in reihe], fenster)
    return {
        "z": _runde(z, 2),
        "markt_schlaeft": None if z is None else z < schwellen["markt_schlaeft_bis_z"],
        "status": "gerechnet" if z is not None else "zu wenige Werte",
        "letzter": reihe[-1],
        "fenster_monate": fenster,
        "einheit": rohstoff["preis"].get("einheit"),
    }


def score(staerke: float | None, zf: float | None, z: float | None, gegen: float | None,
          schwellen: dict) -> dict | None:
    """Score = w1·Stärke + w2·Zeitfenster − w3·Z − w4·Gegenkräfte, dann auf 1 bis 10.

    Z geht normiert ein: Z = 3 ist voller Abzug, ein negativer Z-Wert zieht nichts ab.
    Fehlt ein Faktor, wird ohne ihn gerechnet und neu auf 1 bis 10 gestreckt.
    """
    g = schwellen["gewichte"]
    z_norm = None if z is None else begrenze(z / schwellen["z_voll_bei"])
    faktoren = {"staerke": (staerke, 1), "zeitfenster": (zf, 1),
                "zwert": (z_norm, -1), "gegenkraefte": (gegen, -1)}
    summe = plus = minus = 0.0
    fehlend = []
    for name, (wert, vorzeichen) in faktoren.items():
        if wert is None:
            fehlend.append(name)
            continue
        summe += vorzeichen * g[name] * wert
        if vorzeichen > 0:
            plus += g[name]
        else:
            minus += g[name]
    if plus == 0:
        return None
    zahl = math.floor(1 + 9 * (summe + minus) / (plus + minus) + 0.5)
    return {"wert": round(summe, 3), "zahl": int(zahl), "vorlaeufig": True, "fehlend": fehlend}


def _status(wert: bool | None) -> str:
    return "unbekannt" if wert is None else ("ja" if wert else "nein")


def checkliste(enso_lage: dict | None, zf: dict, gegen: dict, probe: dict, schwellen: dict) -> list[dict]:
    episode = (enso_lage or {}).get("episode")
    if enso_lage is None:
        p1, text1 = None, "El-Niño-Index heute nicht lesbar"
    elif not episode:
        p1, text1 = False, "kein El Niño, der noch wirkt"
    elif zf["wert"] == 0:
        p1, text1 = False, "El Niño vorbei, Zeitfenster abgelaufen"
    else:
        hoch = episode["hoehepunkt"]
        text1 = (f"El Niño {'läuft' if episode['laeuft'] else 'vorbei, wirkt nach'}, "
                 f"bisher höchster Wert {hoch['wert']:+.1f} ({hoch['jahreszeit']} {hoch['jahr']})")
        p1 = True

    if zf["wert"] is None:
        p2, text2 = None if enso_lage is None else False, zf["status"]
    else:
        p2 = zf["wert"] > 0
        knapp = 0 < zf["wert"] <= schwellen["zeitfenster_knapp_ab"]
        text2 = f"Zeitfenster {zf['wert']:.2f} ({zf['status']})" + (", knapp" if knapp else "")

    p3 = None if gegen["ueberwiegen"] is None else not gegen["ueberwiegen"]
    text3 = ("Gegenkräfte unbekannt" if gegen["wert"] is None
             else f"Druck der Gegenkräfte {gegen['wert']:.2f}")
    p4 = probe["markt_schlaeft"]
    text4 = ("Preisprobe fehlt" if probe["z"] is None
             else f"Z-Wert des Preises {probe['z']:+.2f}")
    return [
        {"nr": 1, "punkt": "Auslöser", "frage": "Wirkt ein El Niño?", "status": _status(p1), "text": text1},
        {"nr": 2, "punkt": "Zeitfenster", "frage": "Ist das Zeitfenster noch offen?", "status": _status(p2), "text": text2},
        {"nr": 3, "punkt": "Gegenkräfte", "frage": "Überwiegen die Gegenkräfte nicht?", "status": _status(p3), "text": text3},
        {"nr": 4, "punkt": "Preisprobe", "frage": "Schläft der Markt noch?", "status": _status(p4), "text": text4},
    ]


# ------------------------------------------------------------------ Ampel
def ampel(rohstoff: dict, punkte: list[dict], zf: dict, dipol_lage: dict | None,
          score_ergebnis: dict | None, schwellen: dict) -> dict:
    status = {p["nr"]: p["status"] for p in punkte}
    if status[1] == "unbekannt":
        return {"farbe": OHNE_URTEIL, "zahl": None, "gruende": [punkte[0]["text"]], "rot_bedingungen": []}
    if status[1] != "ja":
        return {"farbe": "Grün", "zahl": None, "gruende": [punkte[0]["text"]], "rot_bedingungen": []}

    knapp = zf["wert"] is not None and 0 < zf["wert"] <= schwellen["zeitfenster_knapp_ab"]
    bedingungen = [
        {"name": "Zeitfenster knapp", "erfuellt": knapp},
        {"name": "Gegenkräfte überwiegen nicht", "erfuellt": {"ja": True, "nein": False}.get(status[3])},
        {"name": "Markt schläft noch", "erfuellt": {"ja": True, "nein": False}.get(status[4])},
    ]
    if "dipol" in rohstoff.get("kopplungen", []):
        kreuz = (dipol_lage or {}).get("kreuz") or {}
        bedingungen += [
            {"name": "Ostende der Kaskade bestätigt",
             "erfuellt": None if dipol_lage is None else dipol_lage["ostende_bestaetigt"]},
            {"name": "Kreuzbestätigung West und Ost",
             "erfuellt": None if not kreuz else kreuz["bestaetigt"], "stand": kreuz.get("urteil")},
        ]
    offen = [b for b in bedingungen if b["erfuellt"] is not True]
    farbe = "Rot" if not offen else "Gelb"
    gruende = []
    for b in offen:
        zusatz = "unbekannt" if b["erfuellt"] is None else "nein"
        if b.get("stand"):
            zusatz = b["stand"]
        gruende.append(f"{b['name']}: {zusatz}")
    return {"farbe": farbe, "zahl": score_ergebnis["zahl"] if score_ergebnis else None,
            "gruende": gruende or ["alle Bedingungen für Rot erfüllt"], "rot_bedingungen": bedingungen}


def veto_anwenden(ergebnis: dict, kennung: str, veto: dict, heute: date) -> dict:
    """Politik-Veto als letzte Schicht. Wirkungen: sperren, hochstufen, herabstufen.

    hochstufen hebt höchstens auf Gelb: Rot kommt nur aus der Checkliste.
    """
    treffer, fehler = [], []
    for eintrag in (veto or {}).get("aktiv") or []:
        if eintrag.get("rohstoff") != kennung:
            continue
        try:
            seit, bis = _datum(eintrag.get("seit")), _datum(eintrag.get("bis"))
        except ValueError:
            fehler.append(f"veto.yaml: Datum bei „{eintrag.get('grund', kennung)}“ nicht lesbar, "
                          "bitte als JJJJ-MM-TT eintragen; Eintrag bleibt unberücksichtigt")
            continue
        if eintrag.get("wirkung") not in ("sperren", "hochstufen", "herabstufen"):
            fehler.append(f"veto.yaml: Wirkung „{eintrag.get('wirkung')}“ unbekannt "
                          "(erlaubt: sperren, hochstufen, herabstufen)")
            continue
        if (seit and heute < seit) or (bis and heute > bis):
            continue
        treffer.append(eintrag)

    farbe = ergebnis["farbe"]
    gesperrt = False
    for eintrag in treffer:
        wirkung = eintrag["wirkung"]
        if farbe in STUFEN and wirkung == "hochstufen":
            farbe = STUFEN[max(STUFEN.index(farbe), 1)]
        elif farbe in STUFEN and wirkung == "herabstufen":
            farbe = STUFEN[max(STUFEN.index(farbe) - 1, 0)]
        elif wirkung == "sperren":
            gesperrt = True
    zahl = ergebnis.get("zahl")
    anzeige = farbe if zahl is None or farbe in ("Grün", OHNE_URTEIL) else f"{farbe}, {zahl}"
    if gesperrt:
        anzeige = f"gesperrt ({anzeige})"
    return {
        **ergebnis,
        "farbe_rechnung": ergebnis["farbe"],
        "farbe": farbe,
        "gesperrt": gesperrt,
        "anzeige": anzeige,
        "veto": [{k: str(v) if isinstance(v, date) else v for k, v in e.items()} for e in treffer],
        "veto_fehler": fehler,
    }


def _datum(wert) -> date | None:
    if wert is None or wert == "":
        return None
    if isinstance(wert, date):
        return wert
    return date.fromisoformat(str(wert).strip())


# ------------------------------------------------------------------ Instrumente
def instrumente(rohstoff: dict, kurse: dict[str, list[dict]], fehler: dict[str, str],
                schwellen_kurse: dict) -> list[dict]:
    """Kennzahlen je Aktie oder ETC: letzter Kurs, Z-Wert (200 Tage), drei Monate, Volumen."""
    liste = []
    for inst in rohstoff.get("instrumente", []):
        reihe = kurse.get(inst["ticker"]) or []
        eintrag = {k: inst.get(k) for k in ("art", "name", "ticker", "boerse", "hinweis")}
        if not reihe:
            eintrag["status"] = fehler.get(inst["ticker"], "keine Kurse")
        else:
            letzter = reihe[-1]
            eintrag.update({
                "status": "ok" if inst["ticker"] not in fehler else f"Archiv, heute: {fehler[inst['ticker']]}",
                "kurs": letzter["schluss"],
                "datum": letzter["datum"],
                "z_200": _runde(zwert([e["schluss"] for e in reihe], schwellen_kurse["z_fenster_tage"]), 2),
                "veraenderung_3m": _runde(veraenderung(reihe, 91)),
                "volumen_trend": _runde(volumen_trend(reihe), 2),
            })
        liste.append(eintrag)
    return liste


# ------------------------------------------------------------------ Gesamt
def bewerte(rohstoff: dict, enso_lage: dict | None, dipol_lage: dict | None,
            preisreihe: list[dict] | None, gegen_reihen: dict[str, list[dict]],
            kurse: dict[str, list[dict]], kursfehler: dict[str, str],
            schwellen: dict, veto: dict, heute: date) -> dict:
    grund = {"name": rohstoff["name"], "kennung": rohstoff["kennung"], "familie": rohstoff["familie"],
             "treiber": rohstoff["treiber"], "rolle": rohstoff.get("rolle")}
    if rohstoff["treiber"] != "klima" or rohstoff.get("ausloeser") != "enso":
        return {**grund, "ampel": None,
                "hinweis": f"Rechenweg für Treiber {rohstoff['treiber']} ist noch nicht gebaut"}

    s = schwellen["agrar_ampel"]
    T = rohstoff["vorlauf_T_monate"]
    zf = enso.zeitfenster(enso_lage, T)
    gegen = gegenkraefte(rohstoff, gegen_reihen, s)
    probe = preisprobe(rohstoff, preisreihe, s)
    punkte = checkliste(enso_lage, zf, gegen, probe, s)
    staerke = (enso_lage or {}).get("staerke") if (enso_lage or {}).get("episode") else None
    ohne_zf = bool(s.get("zahl_ohne_zeitfenster"))
    sc = score(staerke, None if ohne_zf else zf["wert"], probe["z"], gegen["wert"], s) \
        if punkte[0]["status"] == "ja" else None
    if sc and ohne_zf:
        # Das Zeitfenster fehlt nicht, es ist bewusst nicht Teil der Zahl (Beschluss 26.09.2026).
        sc["fehlend"] = [f for f in sc["fehlend"] if f != "zeitfenster"]
        sc["ohne_zeitfenster"] = True
    roh = ampel(rohstoff, punkte, zf, dipol_lage, sc, s)
    return {
        **grund,
        "ampel": veto_anwenden(roh, rohstoff["kennung"], veto, heute),
        "checkliste": punkte,
        "zeitfenster": zf,
        "gegenkraefte": gegen,
        "preisprobe": probe,
        "score": sc,
        "instrumente": instrumente(rohstoff, kurse, kursfehler, schwellen["kurse"]),
    }
