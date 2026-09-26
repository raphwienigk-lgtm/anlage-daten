"""Zahlen und Daten zum Vorlesen: ausgeschrieben, wie im Vorlese-Format verlangt."""
from __future__ import annotations

from datetime import date

_EINER = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
          "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn",
          "achtzehn", "neunzehn"]
_ZEHNER = {2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig", 6: "sechzig",
           7: "siebzig", 8: "achtzig", 9: "neunzig"}
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
_ORDNUNG = {1: "ersten", 3: "dritten", 7: "siebten", 8: "achten"}


def _unter_hundert(n: int, am_ende: bool) -> str:
    if n < 20:
        if n == 1 and not am_ende:
            return "ein"
        return _EINER[n]
    zehner, einer = divmod(n, 10)
    if einer == 0:
        return _ZEHNER[zehner]
    return ("ein" if einer == 1 else _EINER[einer]) + "und" + _ZEHNER[zehner]


def _unter_tausend(n: int, am_ende: bool = True) -> str:
    hunderter, rest = divmod(n, 100)
    teil = ""
    if hunderter:
        teil = ("ein" if hunderter == 1 else _EINER[hunderter]) + "hundert"
    if rest:
        teil += _unter_hundert(rest, am_ende)
    return teil


def wort(n: int) -> str:
    """Ganze Zahl in Worten, bis 999 999. 21 → einundzwanzig, 2026 → zweitausendsechsundzwanzig."""
    n = int(n)
    if n < 0:
        return "minus " + wort(-n)
    if n == 0:
        return "null"
    if n >= 1_000_000:
        return str(n)
    tausender, rest = divmod(n, 1000)
    teil = ""
    if tausender:
        teil = ("ein" if tausender == 1 else _unter_tausend(tausender, am_ende=False)) + "tausend"
    if rest:
        teil += _unter_tausend(rest)
    return teil


def jahr(n: int) -> str:
    """Jahreszahl, wie man sie spricht: 1998 → neunzehnhundertachtundneunzig, 2026 → zweitausendsechsundzwanzig."""
    n = int(n)
    if 1100 <= n <= 1999:
        rest = n % 100
        return wort(n // 100) + "hundert" + (wort(rest) if rest else "")
    return wort(n)


def komma(x: float, stellen: int = 1, vorzeichen: bool = False) -> str:
    """0,83 → „null Komma acht drei“. Mit vorzeichen: „plus eins Komma zwei“."""
    gerundet = round(x, stellen)
    text = f"{abs(gerundet):.{stellen}f}"
    ganz, _, nach = text.partition(".")
    teile = wort(int(ganz))
    nach = nach.rstrip("0")
    if nach:
        teile += " Komma " + " ".join(_EINER[int(z)] for z in nach)
    if gerundet < 0:
        return "minus " + teile
    if vorzeichen and gerundet > 0:
        return "plus " + teile
    return teile


def prozent(anteil: float) -> str:
    """0,82 → „zweiundachtzig Prozent“."""
    return wort(round(anteil * 100)) + " Prozent"


def veraenderung(anteil: float) -> str:
    """−0,124 → „zwölf Prozent gefallen“."""
    p = round(anteil * 100)
    if p == 0:
        return "kaum verändert"
    return f"{wort(abs(p))} Prozent {'gestiegen' if p > 0 else 'gefallen'}"


def ordnungszahl(n: int) -> str:
    """Tag im Datum: 1 → ersten, 25 → fünfundzwanzigsten."""
    if n in _ORDNUNG:
        return _ORDNUNG[n]
    if n < 20:
        return wort(n) + "ten"
    return wort(n) + "sten"


def datum(d: date, mit_jahr: bool = False) -> str:
    text = f"{ordnungszahl(d.day)} {MONATE[d.month - 1]}"
    return text + (f" {jahr(d.year)}" if mit_jahr else "")


def aufzaehlung(teile: list[str]) -> str:
    """„a“, „a und b“, „a, b und c“."""
    if not teile:
        return ""
    if len(teile) == 1:
        return teile[0]
    return ", ".join(teile[:-1]) + " und " + teile[-1]


def tage(liste: list[date]) -> str:
    """Mehrere Tage, der Monat nur einmal je Gruppe: „zwanzigsten und einundzwanzigsten September“."""
    gruppen: list[tuple[int, list[str]]] = []
    for d in sorted(liste):
        if gruppen and gruppen[-1][0] == d.month:
            gruppen[-1][1].append(ordnungszahl(d.day))
        else:
            gruppen.append((d.month, [ordnungszahl(d.day)]))
    return aufzaehlung([f"{aufzaehlung(t)} {MONATE[m - 1]}" for m, t in gruppen])


def monat(jahr_nr: int, monat_nr: int) -> str:
    return f"{MONATE[monat_nr - 1]} {jahr(jahr_nr)}"


JAHRESZEITEN_TEXT = {
    "DJF": "Dezember bis Februar", "JFM": "Januar bis März", "FMA": "Februar bis April",
    "MAM": "März bis Mai", "AMJ": "April bis Juni", "MJJ": "Mai bis Juli",
    "JJA": "Juni bis August", "JAS": "Juli bis September", "ASO": "August bis Oktober",
    "SON": "September bis November", "OND": "Oktober bis Dezember", "NDJ": "November bis Januar",
}


def jahreszeit(kuerzel: str, jahr_nr: int) -> str:
    """NOAA-Schreibweise: NDJ 2026 = November 2026 bis Januar 2027, DJF 2027 = Dezember 2026 bis Februar 2027."""
    text = JAHRESZEITEN_TEXT.get(kuerzel, kuerzel)
    if kuerzel == "NDJ":
        anfang, _, ende = text.partition(" bis ")
        return f"{anfang} {jahr(jahr_nr)} bis {ende}"
    return f"{text} {jahr(jahr_nr)}"
