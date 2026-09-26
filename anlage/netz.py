"""Abrufe aus dem Netz, mit Wiederholung bei vorübergehenden Fehlern."""
from __future__ import annotations

import time

import requests

KENNUNG = "anlage-beobachter/0.1 (privates Frühwarnsystem; github.com/raphwienigk-lgtm/anlage-daten)"


class AbrufFehler(RuntimeError):
    """Eine Quelle war nicht erreichbar oder lieferte nichts Brauchbares."""


def _abruf(url: str, params: dict | None = None, versuche: int = 3, timeout: int = 45) -> requests.Response:
    letzter = None
    for nr in range(versuche):
        try:
            antwort = requests.get(url, params=params, timeout=timeout,
                                   headers={"User-Agent": KENNUNG})
            if antwort.status_code == 429:
                raise AbrufFehler(f"Tageslimit oder Ratenlimit erreicht (429) bei {url}")
            if 400 <= antwort.status_code < 500:
                auszug = " ".join(antwort.text[:300].split())
                raise AbrufFehler(f"Fehler {antwort.status_code} bei {url}" + (f": {auszug}" if auszug else ""))
            if antwort.status_code >= 500:
                letzter = AbrufFehler(f"Serverfehler {antwort.status_code} bei {url}")
            else:
                return antwort
        except AbrufFehler:
            raise
        except requests.RequestException as fehler:
            letzter = AbrufFehler(f"{type(fehler).__name__} bei {url}: {fehler}")
        time.sleep(2 * (nr + 1))
    raise letzter or AbrufFehler(f"Abruf fehlgeschlagen: {url}")


def hole_text(url: str, params: dict | None = None) -> str:
    return _abruf(url, params).text


def hole_json(url: str, params: dict | None = None):
    antwort = _abruf(url, params)
    try:
        return antwort.json()
    except ValueError as fehler:
        raise AbrufFehler(f"Keine JSON-Antwort von {url}") from fehler
