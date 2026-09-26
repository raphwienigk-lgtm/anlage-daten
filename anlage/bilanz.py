"""Bilanz einer Ampel: Was hätte Rot gebracht? Gemeinsam für Rückblick und Nachprüfer.

Eingang ist ein Monatsverlauf der Ampel [{monat: 'JJJJ-MM', farbe, ...}] (oder das
Signal-Logbuch) und eine Monatsreihe des Preises [{datum: 'JJJJ-MM-TT', wert}].

Regeln wie im Schattendepot:
- Rot eröffnet einen gedachten Kauf, wenn keiner offen ist; erst Grün schließt ihn.
  Rot unter einer Veto-Sperre eröffnet nichts.
- Gekauft wird zum Monatsdurchschnitt des Signalmonats.
- Treffer: Der Preis steigt in den zwölf Monaten danach irgendwann um mindestens
  `treffer_ab`. Fehlalarm: Er tut es nicht. Offen: Die zwölf Monate sind noch nicht
  vorbei oder reichen über die Grenze (Lernzeit endet, Prüfzeit bleibt unberührt).
- Mehrwert: mittlere Veränderung zwölf Monate nach Rot minus mittlere Veränderung
  über alle Monate desselben Zeitraums.
- Zufallsprobe: Anteil von Ziehungen gleich vieler zufälliger Monate, die im Mittel
  mindestens so gut abschneiden. Klein heißt: kaum durch Glück zu erklären.
"""
from __future__ import annotations

import random
from collections import Counter
from statistics import mean

HORIZONT = 12
ZIEHUNGEN = 10_000


# ------------------------------------------------------------------ Monate
def monats_index(text: str) -> int:
    """'1997-08' oder '1997-08-01' → fortlaufende Monatsnummer."""
    return int(text[:4]) * 12 + int(text[5:7]) - 1


def monat_text(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def preis_nach_monat(reihe: list[dict] | None, bis: int | None = None) -> dict[int, float]:
    """Monatsreihe → {Monatsnummer: Wert}; Werte hinter `bis` bleiben weg."""
    ergebnis = {}
    for e in reihe or []:
        i = monats_index(e["datum"])
        if e.get("wert") and (bis is None or i <= bis):
            ergebnis[i] = float(e["wert"])
    return ergebnis


def _vollstaendig(preise: dict[int, float], i: int, h: int) -> bool:
    return all(j in preise for j in range(i, i + h + 1))


def veraenderung(preise: dict[int, float], i: int, h: int) -> float | None:
    if i in preise and i + h in preise and preise[i]:
        return preise[i + h] / preise[i] - 1
    return None


def max_anstieg(preise: dict[int, float], i: int, h: int = HORIZONT) -> tuple[float, int] | None:
    """Höchster Stand in den h Monaten nach i, relativ zu i, und sein Monat (bei Gleichstand der frühere)."""
    if not _vollstaendig(preise, i, h) or not preise[i]:
        return None
    gipfel = max(range(i + 1, i + h + 1), key=lambda j: (preise[j], -j))
    return preise[gipfel] / preise[i] - 1, gipfel


def max_rueckgang(preise: dict[int, float], i: int, h: int = HORIZONT) -> float | None:
    if not _vollstaendig(preise, i, h) or not preise[i]:
        return None
    return min(preise[j] for j in range(i + 1, i + h + 1)) / preise[i] - 1


# ------------------------------------------------------------------ Signale
def signale(verlauf: list[dict]) -> list[dict]:
    """Gedachte Käufe aus einem Monatsverlauf. „ohne Urteil“ ändert nichts."""
    liste, offen = [], None
    for eintrag in verlauf:
        farbe = eintrag.get("farbe")
        if farbe == "Rot" and offen is None and not eintrag.get("gesperrt"):
            offen = {"monat": eintrag["monat"], "zahl": eintrag.get("zahl"), "schluss": None}
            liste.append(offen)
        elif farbe == "Grün" and offen is not None:
            offen["schluss"] = eintrag["monat"]
            offen = None
    return liste


def signale_aus_logbuch(eintraege: list[dict], kennung: str) -> list[dict]:
    """Dieselbe Liste aus dem Signal-Logbuch des täglichen Laufs (für den Nachprüfer)."""
    liste, offen = [], None
    for e in eintraege:
        if e.get("rohstoff") != kennung:
            continue
        if e.get("schattenkauf") and offen is None:
            offen = {"monat": e["zeit"][:7], "zeit": e["zeit"], "zahl": e.get("zahl"), "schluss": None,
                     "rohstoffpreis": e.get("rohstoffpreis"), "kurse": e.get("kurse")}
            liste.append(offen)
        elif e.get("schattenschluss") and offen is not None:
            offen["schluss"] = e["zeit"][:7]
            offen = None
    return liste


def bewerte_signal(signal: dict, preise: dict[int, float], treffer_ab: float) -> dict:
    """Ergänzt ein Signal um die Veränderungen danach und das Urteil Treffer, Fehlalarm oder offen."""
    i = monats_index(signal["monat"])
    ergebnis = {**signal, "preis": preise.get(i)}
    for h in (3, 6, 12):
        ergebnis[f"nach_{h}"] = _runde(veraenderung(preise, i, h))
    anstieg = max_anstieg(preise, i)
    if anstieg is None:
        ergebnis.update({"urteil": "offen", "hoechster": None, "gipfel_nach_monaten": None, "tiefster": None})
    else:
        ergebnis.update({
            "urteil": "Treffer" if anstieg[0] >= treffer_ab else "Fehlalarm",
            "hoechster": _runde(anstieg[0]),
            "gipfel_nach_monaten": anstieg[1] - i,
            "tiefster": _runde(max_rueckgang(preise, i)),
        })
    if signal.get("schluss"):
        ergebnis["bei_schluss"] = _runde(veraenderung(preise, i, monats_index(signal["schluss"]) - i))
    return ergebnis


def _runde(x: float | None, stellen: int = 4) -> float | None:
    return None if x is None else round(x, stellen)


# ------------------------------------------------------------------ Vergleich
def basis(preise: dict[int, float], von: int, bis: int, treffer_ab: float) -> dict:
    """Was ohne Ampel passiert: alle Monate von `von` bis `bis` mit vollen zwölf Monaten danach."""
    werte, treffer = [], 0
    for i in range(von, bis + 1):
        v = veraenderung(preise, i, HORIZONT)
        a = max_anstieg(preise, i)
        if v is None or a is None:
            continue
        werte.append(v)
        treffer += a[0] >= treffer_ab
    return {"monate": len(werte), "werte": werte,
            "mittel_12": _runde(mean(werte)) if werte else None,
            "trefferquote": _runde(treffer / len(werte)) if werte else None}


def zufallsprobe(alle: list[float], n: int, beobachtet: float, ziehungen: int = ZIEHUNGEN,
                 saat: int = 1960) -> float | None:
    """Anteil der Ziehungen von n zufälligen Monaten, deren Mittel mindestens `beobachtet` erreicht."""
    if n == 0 or len(alle) < n:
        return None
    zufall = random.Random(saat)
    besser = sum(1 for _ in range(ziehungen) if sum(zufall.sample(alle, n)) / n >= beobachtet - 1e-12)
    return round(besser / ziehungen, 4)


# ------------------------------------------------------------------ Große Bewegungen
def _el_nino(beginn: int, verlauf: dict[int, dict], ereignisse: list[int] | None,
             fenster: tuple[int, int]) -> bool:
    if ereignisse is not None:
        return any(p + fenster[0] <= beginn <= p + fenster[1] for p in ereignisse)
    return bool((verlauf.get(beginn) or {}).get("episode"))


def bewegungen(preise: dict[int, float], von: int, bis: int, schwelle: float, vorher: int,
               verlauf: dict[int, dict], positionen: list[dict], ereignisse: list[int] | None = None,
               fenster: tuple[int, int] = (-3, HORIZONT)) -> list[dict]:
    """Anstiege um mindestens `schwelle` innerhalb von zwölf Monaten, und was die Ampel dazu sagte.

    Monate, von denen aus der Preis binnen zwölf Monaten so stark steigt, bilden Gruppen;
    Beginn ist der tiefste Monat der Gruppe (bei Gleichstand der späteste), Gipfel der
    höchste danach. Eingeordnet wird:
    - rechtzeitig: Eine gedachte Position war spätestens einen Monat nach Beginn offen
      (auch eine ältere; sie schließt ohnehin erst bei Grün).
    - spät: Rot kam erst nach Beginn, aber vor dem Gipfel.
    - nur Gelb: kein Rot, aber Gelb in den `vorher` Monaten vor Beginn bis einen Monat danach.
    - verpasst: nichts davon.
    Mit El Niño heißt: Der Beginn liegt im Fenster eines El-Niño-Höhepunkts (`ereignisse`,
    Monatsnummern), standardmäßig drei Monate davor bis zwölf danach. Ohne `ereignisse`
    zählt, ob im Monat des Beginns eine Episode wirkte.
    """
    kandidaten = [i for i in range(von, bis + 1)
                  if (a := max_anstieg(preise, i)) is not None and a[0] >= schwelle]
    gruppen: list[list[int]] = []
    for i in kandidaten:
        if gruppen and i - gruppen[-1][-1] == 1:
            gruppen[-1].append(i)
        else:
            gruppen.append([i])
    liste = []
    for gruppe in gruppen:
        beginn = min(gruppe, key=lambda i: (preise[i], -i))          # bei Gleichstand der letzte Tiefpunkt
        oben = max(j for j in range(beginn + 1, gruppe[-1] + HORIZONT + 1) if j in preise)
        gipfel = max((j for j in range(beginn + 1, oben + 1) if j in preise), key=lambda j: (preise[j], -j))
        offen = next((p for p in positionen
                      if p["i"] <= beginn + 1 and (p["schluss_i"] is None or p["schluss_i"] > beginn)), None)
        spaet = next((p for p in positionen if beginn + 1 < p["i"] <= gipfel), None)
        gelb = any((verlauf.get(j) or {}).get("farbe") in ("Gelb", "Rot") for j in range(beginn - vorher, beginn + 2))
        if offen:
            einordnung, seit = "rechtzeitig", offen["monat"]
        elif spaet:
            einordnung, seit = "spät", spaet["monat"]
        elif gelb:
            einordnung, seit = "nur Gelb", None
        else:
            einordnung, seit = "verpasst", None
        liste.append({
            "beginn": monat_text(beginn),
            "gipfel": monat_text(gipfel),
            "anstieg": _runde(preise[gipfel] / preise[beginn] - 1),
            "el_nino": _el_nino(beginn, verlauf, ereignisse, fenster),
            "einordnung": einordnung,
            "rot_seit": seit,
        })
    return liste


# ------------------------------------------------------------------ Gesamt
def urteil(zahlen: dict, bestehen: dict) -> dict:
    """Bestanden, wenn alle festgelegten Bedingungen erfüllt sind."""
    gruende = []
    if zahlen["bewertbar"] < bestehen["mindest_signale"]:
        gruende.append({"art": "zu_wenige", "ist": zahlen["bewertbar"], "soll": bestehen["mindest_signale"]})
    else:
        if zahlen["mehrwert"] is None or zahlen["mehrwert"] < bestehen["mehrwert_ab"]:
            gruende.append({"art": "mehrwert", "ist": zahlen["mehrwert"], "soll": bestehen["mehrwert_ab"]})
        if bestehen.get("treffer_mindestens_wie_fehlalarme") and zahlen["treffer"] < zahlen["fehlalarme"]:
            gruende.append({"art": "fehlalarme", "ist": zahlen["fehlalarme"], "soll": zahlen["treffer"]})
        grenze = bestehen.get("zufall_hoechstens")
        if grenze is not None and (zahlen["zufall_anteil"] is None or zahlen["zufall_anteil"] > grenze):
            gruende.append({"art": "zufall", "ist": zahlen["zufall_anteil"], "soll": grenze})
    return {"bestanden": not gruende, "gruende": gruende}


def bilanz(verlauf: list[dict], preisreihe: list[dict], von: str, bis: str, s_rb: dict,
           preis_bis: str | None = None, ereignisse: list[int] | None = None,
           ereignis_fenster: tuple[int, int] = (-3, HORIZONT)) -> dict:
    """Bilanz für die Signalmonate von `von` bis `bis`. Preise hinter `preis_bis` bleiben unberührt.

    `verlauf` darf früher beginnen als `von`: Die Positionen werden über den ganzen Verlauf
    geführt, damit eine vorher eröffnete Position nicht als neues Signal zählt.
    """
    grenze = monats_index(preis_bis) if preis_bis else None
    preise = preis_nach_monat(preisreihe, grenze)
    v, b = monats_index(von), monats_index(bis)
    bisher = [e for e in verlauf if monats_index(e["monat"]) <= b]
    teil = [e for e in bisher if monats_index(e["monat"]) >= v]
    nach_monat = {monats_index(e["monat"]): e for e in bisher}
    treffer_ab = s_rb["treffer_ab"]

    alle = [bewerte_signal(s, preise, treffer_ab) for s in signale(bisher)]
    liste = [s for s in alle if v <= monats_index(s["monat"]) <= b]
    bewertbar = [s for s in liste if s["urteil"] != "offen" and s["nach_12"] is not None]
    vergleich = basis(preise, v, b, treffer_ab)
    mittel = _runde(mean(s["nach_12"] for s in bewertbar)) if bewertbar else None
    mehrwert = (_runde(mittel - vergleich["mittel_12"])
                if mittel is not None and vergleich["mittel_12"] is not None else None)
    zahlen = {
        "anzahl": len(liste),
        "bewertbar": len(bewertbar),
        "treffer": sum(s["urteil"] == "Treffer" for s in liste),
        "fehlalarme": sum(s["urteil"] == "Fehlalarm" for s in liste),
        "offen": sum(s["urteil"] == "offen" for s in liste),
        "mittel_12": mittel,
        "basis_12": vergleich["mittel_12"],
        "basis_trefferquote": vergleich["trefferquote"],
        "basis_monate": vergleich["monate"],
        "mehrwert": mehrwert,
        "zufall_anteil": zufallsprobe(vergleich["werte"], len(bewertbar), mittel) if mittel is not None else None,
    }

    positionen = [{**s, "i": monats_index(s["monat"]),
                   "schluss_i": monats_index(s["schluss"]) if s.get("schluss") else None} for s in alle]
    grosse = bewegungen(preise, v, b, s_rb["bewegung_ab"], s_rb["erkannt_monate_vorher"], nach_monat, positionen,
                        ereignisse, ereignis_fenster)
    zaehlung = Counter(g["einordnung"] for g in grosse)
    zaehlung_el_nino = Counter(g["einordnung"] for g in grosse if g["el_nino"])

    farben = Counter(e.get("farbe") for e in teil)
    engpaesse = Counter(name for e in teil if e.get("farbe") == "Gelb" for name in e.get("fehlt") or [])
    return {
        "von": von, "bis": bis, "preis_bis": preis_bis,
        "monate": len(teil),
        "farben": {f: farben.get(f, 0) for f in ("Grün", "Gelb", "Rot", "ohne Urteil")},
        **zahlen,
        "signale": liste,
        "bewegungen": grosse,
        "bewegungen_zaehlung": {"gesamt": len(grosse), "mit_el_nino": sum(g["el_nino"] for g in grosse),
                                **{k: zaehlung.get(k, 0) for k in ("rechtzeitig", "spät", "nur Gelb", "verpasst")},
                                "el_nino": {k: zaehlung_el_nino.get(k, 0)
                                            for k in ("rechtzeitig", "spät", "nur Gelb", "verpasst")}},
        "engpaesse": dict(engpaesse.most_common()),
        "urteil": urteil(zahlen, s_rb["bestehen"]),
    }
