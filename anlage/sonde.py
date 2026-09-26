"""Quellen-Sonde: holt von neuen Kandidaten-Quellen eine kleine Probe und legt sie ab.

Zweck: Bevor ein Modul für eine neue Quelle geschrieben wird, soll das echte Format
bekannt sein, so wie GitHub es sieht. Die Sonde rechnet nichts. Sie schreibt je Quelle
eine Textdatei nach daten/sonde/ (Adresse, Antwortcode, Größe, Auszug; bei NetCDF die
Variablen und Maße) und eine Übersicht daten/sonde/uebersicht.json.

Aufruf: python -m anlage.sonde [--nur name1,name2]
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import time
import zipfile
from collections import Counter
from datetime import date, timedelta

import requests

from . import konfig, speicher

ORDNER = konfig.DATEN / "sonde"
BROWSER = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/124.0 Safari/537.36")
AUSZUG = 4000


def _hole(url: str, headers: dict | None = None, timeout: int = 90, methode: str = "GET",
          daten: dict | None = None) -> requests.Response:
    kopf = {"User-Agent": BROWSER}
    kopf.update(headers or {})
    if methode == "POST":
        return requests.post(url, data=daten, headers=kopf, timeout=timeout)
    return requests.get(url, headers=kopf, timeout=timeout)


def _kopf(url: str, r: requests.Response) -> list[str]:
    return [f"URL: {url}", f"Status: {r.status_code}", f"Typ: {r.headers.get('Content-Type', '?')}",
            f"Größe: {len(r.content)} Bytes", ""]


def _text(url: str, headers: dict | None = None, auszug: int = AUSZUG, suche: str | None = None) -> str:
    r = _hole(url, headers)
    zeilen = _kopf(url, r)
    text = r.text
    if suche:
        treffer = [m.start() for m in re.finditer(suche, text, flags=re.I)][:5]
        zeilen.append(f"Treffer für '{suche}': {len(treffer)}")
        for t in treffer:
            zeilen.append("--- Ausschnitt ---")
            zeilen.append(text[max(0, t - 600):t + 1400])
    else:
        zeilen.append(text[:auszug])
        if len(text) > auszug:
            zeilen.append(f"... ({len(text) - auszug} Zeichen mehr) ...")
            zeilen.append(text[-1500:])
    return "\n".join(zeilen)


def _netcdf(inhalt: bytes, name: str) -> str:
    zeilen = [f"Magische Bytes: {inhalt[:8]!r}"]
    if inhalt[:2] == b"\x1f\x8b":
        inhalt = gzip.decompress(inhalt)
        zeilen.append(f"entpackt: {len(inhalt)} Bytes, magische Bytes {inhalt[:8]!r}")
    try:
        import netCDF4
    except ImportError:
        zeilen.append("netCDF4 nicht installiert")
        return "\n".join(zeilen)
    with netCDF4.Dataset(name, memory=inhalt) as ds:
        zeilen.append(f"Format: {ds.data_model}")
        zeilen.append("Globale Attribute:")
        for a in ds.ncattrs()[:25]:
            zeilen.append(f"  {a} = {str(getattr(ds, a))[:200]}")
        zeilen.append("Dimensionen:")
        for d, dim in ds.dimensions.items():
            zeilen.append(f"  {d}: {len(dim)}")
        zeilen.append("Variablen:")
        for v, var in ds.variables.items():
            attrs = {a: str(getattr(var, a))[:80] for a in var.ncattrs()[:8]}
            zeilen.append(f"  {v} {var.dimensions} {var.dtype} {attrs}")
            if var.ndim == 1 and len(var) > 0:
                werte = var[:]
                zeilen.append(f"    erste: {list(werte[:3])}  letzte: {list(werte[-3:])}")
        for v, var in ds.variables.items():
            if var.ndim >= 2:
                try:
                    stueck = var[tuple(0 for _ in range(var.ndim - 2)) + (slice(0, 3), slice(0, 3))]
                    zeilen.append(f"  Probe {v}[0,...,:3,:3]: {stueck.tolist()}")
                except Exception as fehler:  # noqa: BLE001
                    zeilen.append(f"  Probe {v}: {fehler}")
    return "\n".join(zeilen)


def _binaer(url: str, art: str) -> str:
    r = _hole(url, timeout=180)
    zeilen = _kopf(url, r)
    if r.status_code != 200:
        zeilen.append(r.text[:1500])
        return "\n".join(zeilen)
    if art == "netcdf":
        zeilen.append(_netcdf(r.content, url.rsplit("/", 1)[-1]))
    return "\n".join(zeilen)


def _letzte_datei(verzeichnis: str, muster: str) -> str:
    text = _hole(verzeichnis).text
    namen = sorted(set(re.findall(muster, text)))
    if not namen:
        raise RuntimeError(f"keine Datei nach Muster {muster} in {verzeichnis}")
    return verzeichnis + namen[-1]


# ------------------------------------------------------------------ einzelne Proben
def ersst_box() -> str:
    return _text("https://coastwatch.pfeg.noaa.gov/erddap/griddap/nceiErsstv5.csv?"
                 "ssta%5B(last-1):1:(last)%5D%5B(0.0)%5D%5B(44):1:(62)%5D%5B(300):1:(340)%5D")


def ersst_info() -> str:
    return _text("https://coastwatch.pfeg.noaa.gov/erddap/info/nceiErsstv5/index.csv", auszug=6000)


def caag_ozean() -> str:
    return _text("https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series/"
                 "globe/ocean/tavg/1/0/1850-2026/data.csv", auszug=600)


def hadsst() -> str:
    seite = "https://www.metoffice.gov.uk/hadobs/hadsst4/data/download.html"
    html = _hole(seite).text
    links = sorted(set(re.findall(r'href="([^"]*monthly_GLOBE[^"]*\.csv)"', html)))
    zeilen = [f"Seite: {seite}", f"Links: {links}"]
    if links:
        link = links[0] if links[0].startswith("http") else requests.compat.urljoin(seite, links[0])
        zeilen.append(_text(link, auszug=500))
    return "\n".join(zeilen)


def amoc_metoffice() -> str:
    return _text("https://climate.metoffice.cloud/formatted_data/amoc_rapid_RAPID.csv", auszug=500)


def rapid() -> str:
    return _binaer("https://rapid.ac.uk/sites/default/files/rapid_data/moc_transports.nc", "netcdf")


def gpcc_uebersicht() -> str:
    return _text("https://opendata.dwd.de/climate_environment/GPCC/", auszug=6000)


def gpcc_monitoring() -> str:
    jahr = date.today().year
    verzeichnis = f"https://opendata.dwd.de/climate_environment/GPCC/monitoring_v2022/{jahr}/"
    datei = _letzte_datei(verzeichnis, r'monitoring_v2022_10_\d{4}_\d{2}\.nc\.gz')
    return f"Verzeichnis: {verzeichnis}\n" + _binaer(datei, "netcdf")


def gpcc_di() -> str:
    jahr = date.today().year
    verzeichnis = f"https://opendata.dwd.de/climate_environment/GPCC/GPCC_DI/{jahr}/"
    datei = _letzte_datei(verzeichnis, r'GPCC_DI_\d{6}\.nc\.gz')
    return f"Verzeichnis: {verzeichnis}\n" + _binaer(datei, "netcdf")


def gpcc_monitoring_1982() -> str:
    verzeichnis = "https://opendata.dwd.de/climate_environment/GPCC/monitoring_v2022/1982/"
    return _text(verzeichnis, auszug=3000)


def queimadas() -> str:
    verzeichnis = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_sat_ref/"
    liste = _hole(verzeichnis).text
    zeilen = [f"Verzeichnis: {verzeichnis}", "Dateien: " + ", ".join(sorted(set(re.findall(r'focos_br_ref_\d{4}\.zip', liste))))]
    url = verzeichnis + "focos_br_ref_2024.zip"
    r = _hole(url, timeout=180)
    zeilen += _kopf(url, r)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        zeilen.append(f"Inhalt: {z.namelist()}")
        with z.open(z.namelist()[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace").read()
    reihen = text.splitlines()
    zeilen.append(f"Zeilen: {len(reihen)}")
    zeilen += reihen[:6]
    kopf = reihen[0].split(",")
    sat, bioma = Counter(), Counter()
    i_sat = kopf.index("satelite") if "satelite" in kopf else None
    i_bio = kopf.index("bioma") if "bioma" in kopf else None
    for z_ in reihen[1:]:
        teile = z_.split(",")
        if i_sat is not None and len(teile) > i_sat:
            sat[teile[i_sat]] += 1
        if i_bio is not None and len(teile) > i_bio:
            bioma[teile[i_bio]] += 1
    zeilen.append(f"Satelliten: {dict(sat)}")
    zeilen.append(f"Biome: {dict(bioma)}")
    return "\n".join(zeilen)


def nrcs() -> str:
    basis = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
    st = _hole(f"{basis}/stations?stationTriplets=*:CA:SNTL&activeOnly=true").json()
    zeilen = [f"Stationen: {len(st)}"]
    zeilen += [json.dumps({k: s.get(k) for k in ("stationTriplet", "name", "latitude", "longitude", "elevation", "beginDate")},
                          ensure_ascii=False) for s in st[:60]]
    trip = ",".join(s["stationTriplet"] for s in st[:5])
    url = (f"{basis}/data?stationTriplets={trip}&elements=WTEQ&duration=DAILY&beginDate=1985-04-01&endDate=1985-04-01"
           "&centralTendencyType=MEDIAN")
    zeilen.append(_text(url, auszug=3000))
    return "\n".join(zeilen)


def openmeteo() -> str:
    return _text("https://archive-api.open-meteo.com/v1/archive?latitude=40.9&longitude=38.4&start_date=2026-01-01"
                 "&end_date=2026-01-03&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,"
                 "et0_fao_evapotranspiration&timezone=UTC&models=era5", auszug=1500)


PIHPS = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.bi.go.id/hargapangan",
         "Accept": "application/json, text/javascript, */*; q=0.01"}


def pihps_baum() -> str:
    return _text("https://www.bi.go.id/hargapangan/WebSite/Home/GetCommoditiesTree", PIHPS, auszug=3000)


def pihps_curah() -> str:
    ende = date.today()
    start = ende - timedelta(days=14)
    return _text("https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataKomoditas?price_type_id=1"
                 f"&comcat_id=com_17&province_id=&regency_id=&market_id=&tipe_laporan=1&start_date={start}"
                 f"&end_date={ende}", PIHPS, auszug=2500)


def pihps_monat() -> str:
    time.sleep(1.5)
    return _text("https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataKomoditas?price_type_id=1"
                 "&comcat_id=cat_9&province_id=&regency_id=&market_id=&tipe_laporan=3&start_date=2017-01-01"
                 "&end_date=2022-12-31", PIHPS, auszug=3000)


def mpob_2026() -> str:
    return _text("https://bepi.mpob.gov.my/admin2/price_local_daily_view_cpo_msia.php?more=Y&jenis=1Y&tahun=2026",
                 auszug=5000)


def mpob_tabelle() -> str:
    """Wie liest das Modul die MPOB-Seite? Dazu Ausschnitte um die Grafikdaten und die Tabelle."""
    from .quellen import inland
    url = "https://bepi.mpob.gov.my/admin2/price_local_daily_view_cpo_msia.php?more=Y&jenis=1Y&tahun=2026"
    text = _hole(url).text
    zeilen = [f"URL: {url}", f"Größe: {len(text)} Zeichen"]
    try:
        reihe = inland.lies_mpob(text, 2026)
        zeilen.append(f"lies_mpob: {len(reihe)} Werte, erste {reihe[:2]}, letzte {reihe[-2:]}")
    except Exception as fehler:  # noqa: BLE001
        zeilen.append(f"lies_mpob: {type(fehler).__name__}: {fehler}")
    tab = inland.tabellenzeilen(text)
    zeilen.append(f"Tabellenzeilen: {len(tab)}")
    zeilen += ["  " + " | ".join(z)[:300] for z in tab[:12]]
    for muster in (r"series\s*:", r"data\s*:\s*\[", r"<!--", r"<td[^>]*>\s*0?1\s*</td>"):
        treffer = [m.start() for m in re.finditer(muster, text)][:3]
        zeilen.append(f"--- {muster}: {len(treffer)} Treffer")
        for t in treffer[:2]:
            zeilen.append(text[max(0, t - 200):t + 1200])
    return "\n".join(zeilen)


def mpob_2021() -> str:
    return _text("https://bepi.mpob.gov.my/admin2/price_local_daily_view_cpo_msia.php?more=Y&jenis=1Y&tahun=2021",
                 auszug=1500)


FPMA = "https://fpma.fao.org/giews/v4/price_module/api/v1"


def fpma_liste() -> str:
    zeilen = []
    for land in ("IDN", "IND"):
        daten = _hole(f"{FPMA}/FpmaSerieDomestic/?iso3_country_code={land}").json()
        eintraege = daten.get("results", daten) if isinstance(daten, dict) else daten
        zeilen.append(f"{land}: {len(eintraege)} Reihen; Schlüssel {list(eintraege[0].keys()) if eintraege else []}")
        for e in eintraege:
            text = json.dumps(e, ensure_ascii=False)
            if re.search(r"rice|oil|National", text, flags=re.I):
                zeilen.append("  " + text[:400])
    return "\n".join(zeilen)


def fpma_reihen() -> str:
    zeilen = []
    for uuid in ("c0b2e88d-8010-4f45-b989-fdf1eb126c10", "0cefa19d-3e7a-4b44-a21a-f3b7ec984e3d",
                 "e8830e09-cde2-46ae-8fd7-916a1982b0e1", "ec0bfeb2-6cf3-48a9-8725-3a8860aeae1f"):
        d = _hole(f"{FPMA}/FpmaSeriePrice/{uuid}/").json()
        punkte = d.get("datapoints", [])
        zeilen.append(f"{uuid}: {len(punkte)} Punkte; Schlüssel {list(d.keys())}")
        zeilen.append("  erste: " + json.dumps(punkte[:2]))
        zeilen.append("  letzte: " + json.dumps(punkte[-2:]))
    return "\n".join(zeilen)


def fca() -> str:
    return _text("https://fcainfoweb.nic.in/", suche=r"Rice")


def eppo() -> str:
    return _text("https://gd.eppo.int/reporting/Rse-2026-08", suche=r"Indonesia|Malaysia|palm|Elaeis")


def ippc() -> str:
    return _text("https://www.ippc.int/en/countries/all/pestreport/", auszug=3000)


# ------------------------------------------------------------------ Metall-Agent
def _mit_leser(url: str, leser, *args) -> str:
    """Rohauszug und das, was der Leser des Metall-Moduls daraus macht."""
    r = _hole(url)
    zeilen = _kopf(url, r) + [r.text[:2500]]
    try:
        ergebnis = leser(r.json(), *args)
        zeilen.append(f"--- Leser: {len(ergebnis)} Einträge")
        zeilen += [json.dumps(e, ensure_ascii=False, default=str)[:400] for e in list(ergebnis)[:5]]
        if isinstance(ergebnis, dict):
            zeilen += [f"{k}: {json.dumps(v, default=str)[:300]}" for k, v in ergebnis.items()]
    except Exception as fehler:  # noqa: BLE001
        zeilen.append(f"--- Leser: {type(fehler).__name__}: {fehler}")
    return "\n".join(zeilen)


def bundesregister() -> str:
    from .metall import quellen as mq
    ab = (date.today() - timedelta(days=365)).isoformat()
    url = ("https://www.federalregister.gov/api/v1/documents.json?conditions%5Bterm%5D=antimony"
           f"&conditions%5Bpublication_date%5D%5Bgte%5D={ab}&per_page=20&order=newest"
           + "".join(f"&fields%5B%5D={f}" for f in mq.FELDER)
           + "".join(f"&conditions%5Bagencies%5D%5B%5D={b}" for b in ("industry-and-security-bureau",
                     "trade-representative-office-of-united-states", "commerce-department",
                     "international-trade-administration", "executive-office-of-the-president")))
    return _mit_leser(url, mq.lies_bundesregister)


def usgs_beben() -> str:
    from .metall import quellen as mq
    ab = (date.today() - timedelta(days=90)).isoformat()
    url = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5"
           f"&starttime={ab}&minlatitude=18&maxlatitude=50&minlongitude=95&maxlongitude=135&orderby=time")
    return _mit_leser(url, mq.lies_erdbeben)


def openmeteo_vorhersage() -> str:
    from .metall import quellen as mq
    orte = [{"kennung": "hechi", "name": "Hechi", "lat": 24.69, "lon": 108.08},
            {"kennung": "lincang", "name": "Lincang", "lat": 23.88, "lon": 100.09}]
    url = ("https://api.open-meteo.com/v1/forecast?latitude=24.69,23.88&longitude=108.08,100.09"
           "&daily=precipitation_sum&past_days=7&forecast_days=7&timezone=Asia%2FShanghai")
    return _mit_leser(url, mq.lies_vorhersage, orte)


def mofcom_robots() -> str:
    """Nur die Regeln lesen: Welche MOFCOM-Seiten dürfen Maschinen abrufen?"""
    return "\n\n".join(_text(f"https://{h}/robots.txt", auszug=1500)
                        for h in ("exportcontrol.mofcom.gov.cn", "english.mofcom.gov.cn", "www.mofcom.gov.cn"))


def psd_nuesse() -> str:
    """Führt USDA PSD Haselnüsse (Filberts)? Für den Rückblick des Haselnuss-Sensors (Ernte der Türkei je Jahr)."""
    zeilen = []
    for datei in ("psd_fruits_vegetables_csv.zip", "psd_treenuts_csv.zip", "psd_alldata_csv.zip"):
        url = f"https://apps.fas.usda.gov/psdonline/downloads/{datei}"
        try:
            r = _hole(url, timeout=180)
        except Exception as fehler:  # noqa: BLE001
            zeilen.append(f"{datei}: {type(fehler).__name__}: {fehler}")
            continue
        zeilen.append(f"{datei}: Status {r.status_code}, {len(r.content)} Bytes")
        if r.status_code != 200:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = z.namelist()[0]
                text = z.read(name).decode("utf-8", errors="replace")
        except Exception as fehler:  # noqa: BLE001
            zeilen.append(f"  kein Zip: {fehler}")
            continue
        kopf, *rest = text.splitlines()
        zeilen.append("  Kopf: " + kopf[:300])
        waren = Counter(z.split(",")[1] for z in rest if re.search(r"Filbert|Hazel|Almond", z, flags=re.I))
        zeilen.append(f"  Waren: {dict(waren)}")
        tuerkei = [z for z in rest if re.search(r"Filbert|Hazel", z, flags=re.I) and "Turkey" in z
                   and "Production" in z][-8:]
        zeilen += ["  " + z[:250] for z in tuerkei]
        if waren:
            break
    return "\n".join(zeilen)


def openmeteo_frost() -> str:
    """Tagesminima Ende März 2014 in Giresun (400 m, ERA5): Zeigt das Archiv den bekannten Frost?"""
    return _text("https://archive-api.open-meteo.com/v1/archive?latitude=40.85&longitude=38.35&elevation=400"
                 "&start_date=2014-03-25&end_date=2014-04-05&daily=temperature_2m_min&timezone=Europe%2FIstanbul"
                 "&models=era5", auszug=1500)


PROBEN = {
    "ersst_box": ersst_box, "ersst_info": ersst_info, "caag_ozean": caag_ozean, "hadsst": hadsst,
    "amoc_metoffice": amoc_metoffice, "rapid": rapid, "gpcc_uebersicht": gpcc_uebersicht,
    "gpcc_monitoring": gpcc_monitoring, "gpcc_monitoring_1982": gpcc_monitoring_1982, "gpcc_di": gpcc_di,
    "queimadas": queimadas, "nrcs": nrcs, "openmeteo": openmeteo,
    "pihps_baum": pihps_baum, "pihps_curah": pihps_curah, "pihps_monat": pihps_monat,
    "mpob_2026": mpob_2026, "mpob_tabelle": mpob_tabelle, "mpob_2021": mpob_2021, "fpma_liste": fpma_liste, "fpma_reihen": fpma_reihen,
    "fca": fca, "eppo": eppo, "ippc": ippc,
    "bundesregister": bundesregister, "usgs_beben": usgs_beben, "openmeteo_vorhersage": openmeteo_vorhersage,
    "mofcom_robots": mofcom_robots, "psd_nuesse": psd_nuesse, "openmeteo_frost": openmeteo_frost,
}


def main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(description="Quellen-Sonde")
    teiler.add_argument("--nur", help="Kommagetrennte Namen der Proben")
    args = teiler.parse_args(argv)
    namen = args.nur.split(",") if args.nur else list(PROBEN)
    uebersicht = speicher.lies_json(ORDNER / "uebersicht.json", {}) or {}
    for name in namen:
        beginn = time.time()
        try:
            text = PROBEN[name]()
            status = "ok"
        except Exception as fehler:  # noqa: BLE001 — jede Probe soll für sich scheitern dürfen
            text = f"Fehler: {type(fehler).__name__}: {fehler}"
            status = "Fehler"
        speicher.schreibe_text(ORDNER / f"{name}.txt", text + "\n")
        uebersicht[name] = {"status": status, "sekunden": round(time.time() - beginn, 1),
                            "zeit": konfig.jetzt().isoformat(timespec="seconds"),
                            "erste_zeile": text.splitlines()[0][:200] if text else ""}
        print(f"{status:6} {name} ({uebersicht[name]['sekunden']} s)")
    speicher.schreibe_json(ORDNER / "uebersicht.json", uebersicht)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
