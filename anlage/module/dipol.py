"""Kaskade Indischer Ozean (Dipol).

Stufe 1: El Niño zieht an (ONI ab +0,5) oder wirkt noch nach.
Stufe 2: ungewöhnlich starke Ostwinde vor Sumatra im Mai und Juni.
Stufe 3: Dipol-Index (DMI) ab +0,4 °C, dazu die Vorhersage des BOM als Handeingabe.

Das Ostende gilt als bestätigt, wenn Stufe 1 und dazu Stufe 2 oder 3 anschlagen.
Kreuzbestätigung: Regen im Osten zu wenig UND Regen im Westen zu viel.

Läuft eine El-Niño-Episode, zählt für Stufe 2, Stufe 3 und die Zeugen, ob sie
seit Beginn der Episode angeschlagen haben (Grundlage „Episode“). Ohne Episode
zählt der heutige Stand (Grundlage „aktuell“), nur zur Anzeige.
"""
from __future__ import annotations

from datetime import date

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def stufe1(enso_lage: dict | None) -> dict:
    if not enso_lage:
        return {"an": None, "status": "keine Daten"}
    episode = enso_lage.get("episode")
    if not episode:
        return {"an": False, "status": "kein El Niño"}
    if episode["laeuft"]:
        return {"an": True, "status": "El Niño läuft"}
    return {"an": True, "status": "El Niño vorbei, wirkt nach"}


def stufe2(wind_jahre: dict, heute: date, schwellen: dict, episode_jahre: list[int] | None) -> dict:
    """wind_jahre: {Jahr: {'anomalie_ms', 'vollstaendig', 'tage'} oder {'fehler': Text}}.

    episode_jahre: None ohne Episode (dann zählt das laufende Jahr), sonst die Jahre,
    deren Mai und Juni zur Episode gehören (kann leer sein).
    Solange weniger als `wind_mindest_tage` gemessen sind, gibt es kein Urteil.
    """
    monate = schwellen["wind_monate"]
    grenze = schwellen["wind_anomalie_ms"]
    mindest = schwellen.get("wind_mindest_tage", 14)

    def bewerte(jahr: int) -> dict:
        wind = wind_jahre.get(jahr)
        if wind is None:
            return {"jahr": jahr, "status": "keine Daten", "an": None}
        if wind.get("fehler"):
            return {"jahr": jahr, "status": wind["fehler"], "an": None}
        if not wind.get("vollstaendig") and wind.get("tage", 0) < mindest:
            return {"jahr": jahr, "status": f"Messung läuft, erst {wind.get('tage', 0)} Tage", "an": None,
                    "anomalie_ms": wind["anomalie_ms"]}
        return {"jahr": jahr, "status": "gemessen" if wind.get("vollstaendig") else "Messung läuft",
                "an": wind["anomalie_ms"] <= grenze, "anomalie_ms": wind["anomalie_ms"]}

    if heute.month >= monate[0]:
        aktuell = bewerte(heute.year)
    else:
        aktuell = {"jahr": heute.year, "an": None,
                   "status": f"noch nicht fällig, gemessen wird ab {MONATE[monate[0] - 1]}"}
    if episode_jahre is None:
        return {"an": aktuell["an"], "grundlage": "aktuell", "aktuell": aktuell, "episode": []}
    episode = [bewerte(j) for j in episode_jahre]
    bewertet = [e for e in episode if e["an"] is not None]
    an = any(e["an"] for e in bewertet) if bewertet else None
    ergebnis = {"an": an, "grundlage": "Episode", "aktuell": aktuell, "episode": episode}
    if not episode_jahre:
        ergebnis["status"] = "kein Mai und Juni in dieser Episode"
    return ergebnis


def stufe3(dmi: list[dict] | None, quelle: str | None, schwellen: dict, ab: date | None,
           bis: date | None = None) -> dict:
    if not dmi:
        return {"an": None, "status": "keine Daten", "quelle": quelle}
    grenze = schwellen["positiv_ab"]
    letzte = dmi[-1]
    folge = 0
    for eintrag in reversed(dmi):
        if eintrag["wert"] >= grenze:
            folge += 1
        else:
            break
    aktuell = {"an": letzte["wert"] >= grenze, "wert": letzte["wert"],
               "monat": f"{letzte['jahr']}-{letzte['monat']:02d}", "monate_in_folge": folge}
    ergebnis = {"status": "gemessen", "quelle": quelle, "aktuell": aktuell}
    if ab is None:
        return {**ergebnis, "an": aktuell["an"], "grundlage": "aktuell"}
    oben = (bis.year, bis.month) if bis else (9999, 12)
    seit = [e for e in dmi if (ab.year, ab.month) <= (e["jahr"], e["monat"]) <= oben]
    if not seit:
        return {**ergebnis, "an": None, "grundlage": "Episode",
                "status": "seit Beginn der Episode noch kein Monatswert"}
    hoch = max(seit, key=lambda e: e["wert"])
    return {**ergebnis, "an": hoch["wert"] >= grenze, "grundlage": "Episode",
            "hoechster_seit_beginn": {"wert": hoch["wert"], "monat": f"{hoch['jahr']}-{hoch['monat']:02d}"}}


def prognose(handeingaben: dict, heute: date, veraltet_nach_tagen: int = 21) -> dict:
    eintrag = (handeingaben or {}).get("bom_iod_prognose") or {}
    if not eintrag.get("stand"):
        return {"status": "nicht eingetragen"}
    stand = eintrag["stand"]
    try:
        stand = stand if isinstance(stand, date) else date.fromisoformat(str(stand).strip())
    except ValueError:
        return {"status": "Datum unlesbar", "fehler": f"handeingaben.yaml: Datum „{eintrag['stand']}“ "
                                                    "nicht lesbar, bitte als JJJJ-MM-TT eintragen"}
    alter = (heute - stand).days
    return {"status": "veraltet" if alter > veraltet_nach_tagen else "eingetragen",
            "stand": stand.isoformat(), "alter_tage": alter,
            "aussage": eintrag.get("aussage"), "richtung": eintrag.get("richtung")}


def kreuzbestaetigung(ost: dict | None, west: dict | None) -> dict:
    """ost, west: je das Urteil des Zeugen (Episode oder aktuell) mit 'an' und 'status'."""
    ost, west = ost or {}, west or {}
    if ost.get("an") is None:
        urteil = "Ostzeuge ohne Urteil"
    elif west.get("an") is None:
        urteil = "Westzeuge ohne Urteil"
    elif ost["an"] and west["an"]:
        urteil = "bestätigt"
    elif ost["an"]:
        urteil = "nur Osten"
    elif west["an"]:
        urteil = "nur Westen"
    else:
        urteil = "keiner"
    return {"urteil": urteil, "bestaetigt": urteil == "bestätigt",
            "ost_status": ost.get("status"), "west_status": west.get("status")}


def lage(enso_lage: dict | None, episode_ab: date | None, episode_bis: date | None,
         episode_jahre: list[int], dmi: list[dict] | None, dmi_quelle: str | None, wind_jahre: dict,
         zeugen: dict, handeingaben: dict, heute: date, schwellen: dict) -> dict:
    """episode_bis: bis wann Dürre, Nässe und Dipol noch zur Episode zählen (None = offen)."""
    s1 = stufe1(enso_lage)
    s2 = stufe2(wind_jahre, heute, schwellen, episode_jahre if episode_ab else None)
    s3 = stufe3(dmi, dmi_quelle, schwellen, episode_ab, episode_bis)
    grundlage = "Episode" if episode_ab else "aktuell"
    ost = zeugen["ost"]["episode"] if episode_ab else zeugen["ost"]["aktuell"]
    west = zeugen["west"]["episode"] if episode_ab else zeugen["west"]["aktuell"]
    return {
        "grundlage": grundlage,
        "episode_ab": episode_ab.isoformat() if episode_ab else None,
        "episode_zaehlt_bis": episode_bis.isoformat() if episode_bis else None,
        "stufe1": s1,
        "stufe2": s2,
        "stufe3": s3,
        "prognose": prognose(handeingaben, heute),
        "ostende_bestaetigt": bool(s1["an"]) and bool(s2["an"] or s3["an"]),
        "zeugen": zeugen,
        "kreuz": kreuzbestaetigung(ost, west),
    }
