"""Inlandspreise in Erzeugerländern: Bank Indonesia (PIHPS), MPOB Malaysia, FAO FPMA.

Regierungen greifen ein, wenn es im eigenen Land teuer wird: Indonesiens Exportstopp
für Palmöl im April 2022 folgte auf knappes, teures Speiseöl im Inland. Diese Reihen
dienen als Frühzeichen für den Politik-Kanal.

Die Formate sind zum Teil interne Schnittstellen ohne Zusage. Jede Leseroutine prüft
deshalb ihr Format und meldet einen Fehler, statt still falsche Zahlen zu liefern.
"""
from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser

from .. import netz

PIHPS_URL = "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataKomoditas"
PIHPS_KOPF = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.bi.go.id/hargapangan",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
MPOB_URL = "https://bepi.mpob.gov.my/admin2/price_local_daily_view_cpo_msia.php"
FPMA_URL = "https://fpma.fao.org/giews/v4/price_module/api/v1/FpmaSeriePrice/{uuid}/"

_TAG = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
MONATE_KURZ = {  # englisch und malaiisch
    "jan": 1, "feb": 2, "mar": 3, "mac": 3, "apr": 4, "may": 5, "mei": 5, "jun": 6, "jul": 7,
    "aug": 8, "ogo": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dis": 12,
}


class FormatFehler(ValueError):
    """Die Antwort hat nicht das erwartete Format."""


def zahl(text) -> float | None:
    """„24,350“ → 24350.0, „3,967.50“ → 3967.5, „-“, „PH“, „NT“ und Leeres → None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip().replace("\xa0", "").replace(" ", "")
    if not t or t in {"-", "--", "PH", "NT", "N/A"}:
        return None
    t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


# ------------------------------------------------------------------ Bank Indonesia PIHPS
def lies_pihps(antwort) -> list[dict]:
    """Die Zeile „Semua Provinsi“ (Landesmittel) als Tagesreihe."""
    zeilen = antwort.get("data") if isinstance(antwort, dict) else antwort
    if not isinstance(zeilen, list) or not zeilen:
        raise FormatFehler("PIHPS: keine Datenzeilen")
    land = next((z for z in zeilen if str(z.get("name", "")).lower().startswith("semua")
                 or z.get("level") == 0), None)
    if land is None:
        raise FormatFehler("PIHPS: Zeile „Semua Provinsi“ fehlt")
    reihe = []
    for schluessel, wert in land.items():
        treffer = _TAG.match(str(schluessel))
        if not treffer:
            continue
        w = zahl(wert)
        if w is None:
            continue
        tag, monat, jahr = (int(x) for x in treffer.groups())
        reihe.append({"datum": date(jahr, monat, tag).isoformat(), "wert": w})
    return sorted(reihe, key=lambda e: e["datum"])


def hole_pihps(ware: str, preisart: int, start: date, ende: date) -> list[dict]:
    parameter = {"price_type_id": preisart, "comcat_id": ware, "province_id": "", "regency_id": "",
                 "market_id": "", "tipe_laporan": 1, "start_date": start.isoformat(), "end_date": ende.isoformat()}
    return lies_pihps(netz.hole_json(PIHPS_URL, parameter, kopf=PIHPS_KOPF))


# ------------------------------------------------------------------ MPOB Malaysia
class _Tabelle(HTMLParser):
    def __init__(self):
        super().__init__()
        self.zeilen: list[list[str]] = []
        self._zeile: list[str] | None = None
        self._zelle: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._zeile = []
        elif tag in ("td", "th") and self._zeile is not None:
            self._zelle = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._zeile is not None and self._zelle is not None:
            self._zeile.append(" ".join("".join(self._zelle).split()))
            self._zelle = None
        elif tag == "tr" and self._zeile is not None:
            if self._zeile:
                self.zeilen.append(self._zeile)
            self._zeile = None

    def handle_data(self, data):
        if self._zelle is not None:
            self._zelle.append(data)


def tabellenzeilen(html: str) -> list[list[str]]:
    t = _Tabelle()
    t.feed(html)
    return t.zeilen


def _monat(zelle: str) -> int | None:
    kurz = zelle.strip().lower()[:3]
    return MONATE_KURZ.get(kurz)


def lies_mpob(html: str, jahr: int) -> list[dict]:
    """Tagestabelle: Zeilen = Tage 01 bis 31, Spalten = Monate."""
    zeilen = tabellenzeilen(html)
    kopf_index, spalten = None, {}
    for i, zeile in enumerate(zeilen):
        monate = {j: _monat(z) for j, z in enumerate(zeile) if _monat(z)}
        if len(monate) >= 2:
            kopf_index, spalten = i, monate
            break
    if kopf_index is None:
        raise FormatFehler("MPOB: keine Kopfzeile mit Monaten gefunden")
    versatz = 0
    reihe = []
    for zeile in zeilen[kopf_index + 1:]:
        if not zeile or not re.fullmatch(r"\d{1,2}", zeile[0].strip()):
            continue
        tag = int(zeile[0])
        # Hat die Kopfzeile eine eigene Spalte für den Tag, passen die Indizes; sonst um eins versetzen.
        if versatz == 0 and len(zeile) == len(spalten) + 1 and min(spalten) == 0:
            versatz = 1
        for j, monat in spalten.items():
            k = j + versatz
            if k >= len(zeile):
                continue
            w = zahl(zeile[k])
            if w is None:
                continue
            try:
                d = date(jahr, monat, tag)
            except ValueError:
                continue
            reihe.append({"datum": d.isoformat(), "wert": w})
    if not reihe:
        raise FormatFehler("MPOB: Tabelle ohne Werte")
    return sorted(reihe, key=lambda e: e["datum"])


def hole_mpob(jahr: int) -> list[dict]:
    html = netz.hole_text(MPOB_URL, {"more": "Y", "jenis": "1Y", "tahun": jahr})
    return lies_mpob(html, jahr)


# ------------------------------------------------------------------ FAO FPMA
def lies_fpma(antwort: dict) -> list[dict]:
    punkte = (antwort or {}).get("datapoints")
    if not isinstance(punkte, list):
        raise FormatFehler("FPMA: keine datapoints")
    reihe = [{"datum": p["date"][:10], "wert": float(p["price_value"])}
             for p in punkte if p.get("date") and p.get("price_value") is not None]
    return sorted(reihe, key=lambda e: e["datum"])


def hole_fpma(uuid: str) -> list[dict]:
    return lies_fpma(netz.hole_json(FPMA_URL.format(uuid=uuid)))
