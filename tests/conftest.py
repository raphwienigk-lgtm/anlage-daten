"""Gemeinsame Hilfen für die Tests: ein nachgebautes Netz mit erfundenen Szenarien.

Kein Test greift auf das echte Netz zu. Die Szenarien sind erfunden und dienen nur
dazu, die Rechenwege durchzuspielen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from anlage import konfig, netz
from anlage.netz import AbrufFehler
from anlage.quellen import klimaindizes, kurse

BEISPIEL = Path(__file__).parent / "beispieldaten"


# ------------------------------------------------------------------ Textformate
def oni_text(werte: dict[tuple[int, int], float]) -> str:
    zeilen = [" SEAS  YR   TOTAL   ANOM"]
    for (jahr, monat), wert in sorted(werte.items()):
        zeilen.append(f"  {klimaindizes.JAHRESZEITEN[monat - 1]} {jahr}  27.00  {wert:5.2f}")
    return "\n".join(zeilen) + "\n"


def monatsreihe_text(werte: dict[tuple[int, int], float], fehlwert: str) -> str:
    jahre = sorted({j for j, _ in werte})
    zeilen = []
    for jahr in jahre:
        spalten = [f"{werte[(jahr, m)]:.3f}" if (jahr, m) in werte else fehlwert for m in range(1, 13)]
        zeilen.append(f"{jahr} " + " ".join(spalten))
    return "\n".join(zeilen) + "\n"


def fred_text(serie: str, werte: dict[tuple[int, int], float]) -> str:
    zeilen = [f"observation_date,{serie}"]
    for (jahr, monat), wert in sorted(werte.items()):
        zeilen.append(f"{jahr}-{monat:02d}-01,{wert}")
    return "\n".join(zeilen) + "\n"


# ------------------------------------------------------------------ Szenario
OST_NORMAL, WEST_NORMAL, WIND_NORMAL = 8.0, 3.0, -3.0


def _ist_ost(lon: float) -> bool:
    return lon > 90


@dataclass
class Szenario:
    heute: date
    oni: dict = field(default_factory=dict)
    dmi: dict = field(default_factory=dict)
    fred: dict = field(default_factory=dict)
    ost_trocken: tuple[date, date] | None = None     # Zeitraum mit halbem Regen im Osten
    west_nass: tuple[date, date] | None = None       # Zeitraum mit 180 % Regen im Westen
    wind_jahr_stark: int | None = None               # Jahr mit 1,5 m/s stärkeren Ostwinden
    kurstrend: dict = field(default_factory=dict)    # Ticker → Rückgang über drei Monate (0,2 = 20 %)
    jma_kaputt: bool = False
    yahoo_kaputt: set = field(default_factory=set)

    def regen(self, lat: float, lon: float, tag: date) -> float:
        if _ist_ost(lon):
            if self.ost_trocken and self.ost_trocken[0] <= tag <= self.ost_trocken[1]:
                return OST_NORMAL * 0.5
            return OST_NORMAL
        if self.west_nass and self.west_nass[0] <= tag <= self.west_nass[1]:
            return WEST_NORMAL * 1.8
        return WEST_NORMAL

    def wind(self, lat: float, lon: float, tag: date) -> float:
        return WIND_NORMAL - (1.5 if tag.year == self.wind_jahr_stark else 0.0)

    def kurs(self, ticker: str, tag: date) -> float:
        basis = 100 * (1 + 0.01 * math.sin(tag.toordinal() / 7))
        rueckgang = self.kurstrend.get(ticker)
        if rueckgang:
            tage_bis_heute = (self.heute - tag).days
            if tage_bis_heute < 91:
                basis *= 1 - rueckgang * (91 - tage_bis_heute) / 91
        return basis


class FalschesNetz:
    def __init__(self, szenario: Szenario):
        self.s = szenario
        self.abrufe: list[tuple[str, dict | None]] = []

    def hole_text(self, url: str, params: dict | None = None, kopf: dict | None = None) -> str:
        self.abrufe.append((url, params))
        if "oni.ascii" in url:
            return oni_text(self.s.oni)
        if "jma.go.jp" in url:
            if self.s.jma_kaputt:
                raise AbrufFehler(f"Fehler 404 bei {url}")
            return monatsreihe_text(self.s.dmi, "99.9")
        if "psl.noaa.gov" in url:
            return monatsreihe_text(self.s.dmi, "-9999.000")
        if "fred" in url:
            return fred_text(params["id"], self.s.fred)
        raise AbrufFehler(f"Unbekannte Adresse im Test: {url}")

    def hole_json(self, url: str, params: dict | None = None, kopf: dict | None = None, timeout: int = 45):
        self.abrufe.append((url, params))
        start = date.fromisoformat(params["start_date"])
        ende = date.fromisoformat(params["end_date"])
        tage = [start + timedelta(days=k) for k in range((ende - start).days + 1)]
        lat, lon = params["latitude"], params["longitude"]
        if "daily" in params:
            return {"daily": {"time": [t.isoformat() for t in tage],
                              params["daily"]: [self.s.regen(lat, lon, t) for t in tage]}}
        zeiten, tempo, richtung = [], [], []
        for t in tage:
            u = self.s.wind(lat, lon, t)
            for stunde in range(24):
                zeiten.append(f"{t.isoformat()}T{stunde:02d}:00")
                tempo.append(abs(u))
                richtung.append(90.0 if u < 0 else 270.0)
        return {"hourly": {"time": zeiten, "wind_speed_10m": tempo, "wind_direction_10m": richtung}}

    def hole_yahoo(self, ticker: str, zeitraum: str = "2y") -> list[dict]:
        if ticker in self.s.yahoo_kaputt:
            raise AbrufFehler(f"Yahoo lieferte keine Kurse für {ticker}")
        ende = self.s.heute - timedelta(days=1)
        tage = {"2y": 2 * 365, "1mo": 31, "5d": 7}[zeitraum]   # unbekannter Zeitraum = Fehler im Test
        reihe = []
        for k in range(tage, -1, -1):
            tag = ende - timedelta(days=k)
            if tag.weekday() < 5:
                reihe.append({"datum": tag.isoformat(), "schluss": round(self.s.kurs(ticker, tag), 4),
                              "volumen": 1_000_000})
        return reihe


# ------------------------------------------------------------------ Szenarien
def _monate(von: tuple[int, int], bis: tuple[int, int]):
    jahr, monat = von
    while (jahr, monat) <= bis:
        yield jahr, monat
        monat += 1
        if monat == 13:
            jahr, monat = jahr + 1, 1


def el_nino_2026() -> dict:
    """Erfundene El-Niño-Episode: Beginn MJJ 2026, Höhepunkt NDJ 2026 mit +1,9, Ende MAM 2027."""
    oni = {m: 0.0 for m in _monate((2020, 1), (2027, 7))}
    verlauf = {(2026, 5): 0.3, (2026, 6): 0.6, (2026, 7): 0.9, (2026, 8): 1.2, (2026, 9): 1.5,
               (2026, 10): 1.7, (2026, 11): 1.85, (2026, 12): 1.9, (2027, 1): 1.75, (2027, 2): 1.4,
               (2027, 3): 1.0, (2027, 4): 0.6, (2027, 5): 0.3, (2027, 6): 0.1}
    oni.update(verlauf)
    return oni


def dmi_2026() -> dict:
    dmi = {m: 0.0 for m in _monate((2020, 1), (2027, 7))}
    dmi.update({(2026, 7): 0.3, (2026, 8): 0.6, (2026, 9): 0.9, (2026, 10): 1.0, (2026, 11): 0.5, (2026, 12): 0.1})
    return dmi


def palmoel_preise(bis: tuple[int, int], letzter: float = 880.0) -> dict:
    werte = {m: 900 + 40 * math.sin(i / 3) for i, m in enumerate(_monate((2018, 1), bis))}
    werte[bis] = letzter
    return {m: round(w, 1) for m, w in werte.items()}


def szenario_rot() -> Szenario:
    """Alles für Rot: Höhepunkt vor acht Monaten bestätigt, Dürre im Osten, Nässe im Westen."""
    return Szenario(
        heute=date(2027, 8, 15),
        oni={k: v for k, v in el_nino_2026().items() if k <= (2027, 6)},
        dmi=dmi_2026(),
        fred=palmoel_preise((2027, 6)),
        ost_trocken=(date(2026, 7, 1), date(2026, 10, 31)),
        west_nass=(date(2026, 10, 1), date(2026, 12, 31)),
        wind_jahr_stark=2026,
    )


def szenario_neutral() -> Szenario:
    oni = {m: 0.0 for m in _monate((2020, 1), (2026, 7))}
    return Szenario(heute=date(2026, 9, 26), oni=oni,
                    dmi={m: 0.1 for m in _monate((2020, 1), (2026, 8))},
                    fred=palmoel_preise((2026, 8)))


# ------------------------------------------------------------------ Fixtures
@pytest.fixture
def ablage(tmp_path, monkeypatch):
    """Leitet daten/ und abgabe/ in ein leeres Testverzeichnis um."""
    daten = tmp_path / "daten"
    monkeypatch.setattr(konfig, "DATEN", daten)
    monkeypatch.setattr(konfig, "KLIMA", daten / "klima")
    monkeypatch.setattr(konfig, "PREISE", daten / "preise")
    monkeypatch.setattr(konfig, "ABGABE", tmp_path / "abgabe")
    monkeypatch.setattr(konfig, "GESCHICHTE", daten / "geschichte")
    monkeypatch.setattr(konfig, "RUECKBLICK", daten / "rueckblick")
    monkeypatch.setattr(konfig, "INLAND", daten / "inland")
    return tmp_path


@pytest.fixture
def netz_mit(monkeypatch):
    """Schaltet ein erfundenes Szenario als Netz ein und gibt das falsche Netz zurück."""
    def einschalten(szenario: Szenario) -> FalschesNetz:
        falsch = FalschesNetz(szenario)
        monkeypatch.setattr(netz, "hole_text", falsch.hole_text)
        monkeypatch.setattr(netz, "hole_json", falsch.hole_json)
        monkeypatch.setattr(kurse, "hole_yahoo", falsch.hole_yahoo)
        return falsch
    return einschalten


@pytest.fixture
def schwellen():
    return konfig.lade_yaml(konfig.KONFIG / "schwellen.yaml")
