"""Pfade und Konfiguration."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

BASIS = Path(__file__).resolve().parents[1]
KONFIG = BASIS / "konfig"
DATEN = BASIS / "daten"
KLIMA = DATEN / "klima"
PREISE = DATEN / "preise"
ABGABE = BASIS / "abgabe"
GESCHICHTE = DATEN / "geschichte"
RUECKBLICK = DATEN / "rueckblick"
INLAND = DATEN / "inland"
ZEITZONE = ZoneInfo("Europe/Berlin")


def lade_yaml(pfad: Path) -> dict:
    with open(pfad, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def konfiguration() -> dict:
    """Liest alle Konfigurationsdateien in ein Wörterbuch."""
    rohstoffe = {}
    for datei in sorted((KONFIG / "rohstoffe").glob("*.yaml")):
        eintrag = lade_yaml(datei)
        rohstoffe[eintrag["kennung"]] = eintrag
    return {
        "quellen": lade_yaml(KONFIG / "quellen.yaml"),
        "regionen": lade_yaml(KONFIG / "regionen.yaml"),
        "schwellen": lade_yaml(KONFIG / "schwellen.yaml"),
        "handeingaben": lade_yaml(KONFIG / "handeingaben.yaml"),
        "veto": lade_yaml(KONFIG / "veto.yaml"),
        "kalender": lade_yaml(KONFIG / "kalender.yaml") if (KONFIG / "kalender.yaml").exists() else {},
        "rohstoffe": rohstoffe,
    }


PFLICHTFELDER = ["name", "kennung", "familie", "treiber", "rolle", "kopplungen", "preis", "instrumente"]
ERLAUBT = {
    "familie": {"A", "B"},
    "treiber": {"klima", "politik", "struktur"},
    "rolle": {"kandidat", "sensor", "verworfen"},
    "dipol_seite": {"west", "ost", "mitte", "keine"},
}


def pruefe_rohstoff(eintrag: dict, regionen: dict | None = None) -> list[str]:
    """Prüft ein Rohstoff-Formular. Gibt eine Liste verständlicher Fehler zurück (leer = in Ordnung)."""
    fehler = [f"Feld „{f}“ fehlt" for f in PFLICHTFELDER if f not in eintrag]
    for feld, werte in ERLAUBT.items():
        if feld in eintrag and eintrag[feld] not in werte:
            fehler.append(f"„{feld}“ ist „{eintrag[feld]}“, erlaubt sind: {', '.join(sorted(werte))}")
    if eintrag.get("treiber") == "klima":
        for feld in ("ausloeser", "vorlauf_T_monate", "gegenkraefte"):
            if feld not in eintrag:
                fehler.append(f"Feld „{feld}“ fehlt (nötig bei treiber: klima)")
    preis = eintrag.get("preis") or {}
    for feld in ("quelle", "serie", "z_fenster_monate"):
        if feld not in preis:
            fehler.append(f"preis: Feld „{feld}“ fehlt")
    for nr, inst in enumerate(eintrag.get("instrumente") or [], start=1):
        if not inst.get("ticker"):
            fehler.append(f"instrumente Nr. {nr}: Ticker fehlt")
    region = (eintrag.get("indikator") or {}).get("region")
    if regionen is not None and region and region not in regionen:
        fehler.append(f"indikator: Region „{region}“ steht nicht in regionen.yaml")
    return fehler


def jetzt() -> datetime:
    return datetime.now(ZEITZONE)
