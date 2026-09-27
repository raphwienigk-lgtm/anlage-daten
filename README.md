# anlage-daten

Datenlauf des Anlage-Beobachters. Läuft jeden Morgen auf GitHub, ohne Mac. Er holt die
Klimadaten und Kurse, rechnet Kaskade, Checkliste, Score und Ampel und legt das Ergebnis
als Zahlen (`daten/stand.json`) und als Vorlesetext (`abgabe/anlage-teil-1.md`) ab.

Stand des Gerüsts: nur Palmöl, nur der Wächter Klima. Grundsatz: **Formeln in Python,
Urteile bei Claude.** Hier wird gerechnet, nicht entschieden und nichts gekauft.

> Denkhilfe, keine Anlageberatung. Score und Schwellen sind vorläufig, bis das
> Backtesting steht.

> **Achtung, öffentlich:** Das Repository ist öffentlich, damit Claude die Dateien ohne
> Schlüssel lesen kann. Hier gehören keine Depotstände, Kaufkurse oder persönlichen
> Daten hinein. Die bleiben in der Cloud (später beim Depot-Agenten).

---

## Samstag: einrichten (etwa 30 Minuten plus zwei Stunden Wartezeit)

**1. Repository anlegen.** Auf github.com oben rechts „+“ → „New repository“.
Name `anlage-daten`, Sichtbarkeit **Public**, sonst nichts ankreuzen (kein README).

**2. Entpacken und einmal lokal testen (freiwillig, braucht Python 3.10 oder neuer; yfinance läuft nicht mehr unter 3.9).** Mit älterem Python diesen Schritt auslassen: Nach dem Hochladen laufen die Tests ohnehin auf GitHub. Im Terminal:

```bash
cd ~/Downloads/anlage-daten        # dorthin, wo der Ordner entpackt liegt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q                # erwartet: alle Tests bestanden
python -m anlage.pruefen           # prüft vom Mac aus, ob jede Quelle antwortet
```

Der Prüflauf druckt je Quelle `OK` oder `FEHLER` mit Grund. Einzelne Fehler sind noch
kein Hindernis (für den Dipol-Index gibt es zwei Quellen). Die Ergebnisse gern im Chat
zeigen, dann passen wir an.

**3. Hochladen.**

```bash
git init
git add .
git commit -m "Gerüst Anlage-Beobachter, Palmöl"
git branch -M main
git remote add origin https://github.com/raphwienigk-lgtm/anlage-daten.git
git push -u origin main
```

Beim ersten `push` will GitHub eine Anmeldung. Am einfachsten vorher `gh auth login`
(GitHub CLI) oder den Ordner in GitHub Desktop öffnen und dort veröffentlichen.

**4. Auf GitHub die Läufe starten** (geht auch vom iPhone, Reiter „Actions“):

1. Falls GitHub fragt: Workflows aktivieren.
2. **Prüflauf** → „Run workflow“. Dauert eine Minute. Ergebnis steht in der
   Zusammenfassung des Laufs und in `daten/quellen-status.json`.
3. **Klimatologie** → „Run workflow“. Baut einmalig das Normal 1991 bis 2020 für Regen
   und Wind. Dauert etwa **zwei Stunden**, weil Open-Meteo lange Zeiträume mehrfach
   anrechnet. Hält der Lauf vorher an (Zeitbudget oder Tageslimit), einfach noch einmal
   starten; fertige Messpunkte werden übersprungen. Der tägliche Lauf darf währenddessen
   laufen, er meldet dann nur „Klimatologie unvollständig“.
4. **Täglicher Lauf** → „Run workflow“. Danach liegen `daten/stand.json` und
   `abgabe/anlage-teil-1.md` im Repository.

Scheitert der Schritt „Ergebnis sichern“ mit Fehler 403: Settings → Actions → General →
Workflow permissions → „Read and write permissions“ → Save.

Ab dann läuft der tägliche Lauf von selbst um **02:30 UTC** (04:30 Uhr Sommerzeit,
03:30 Uhr Winterzeit). GitHub startet geplante Läufe manchmal bis zu einer halben
Stunde später. Schlägt ein Lauf fehl, schickt GitHub eine Mail.

**In der Cloud** holt der Wächter Agrarrohstoffe (alle drei Stunden, seit 27.09.2026; vorher
Meldungs-Wächter und Anlage-Bewerter) die Ergebnisse ab, sobald ein neuer Stand da ist, legt
ein Mail-Veto darüber und schreibt den Bericht ins Projekt, Stichwort „Anlagen“.

---

## Was wo liegt

| Pfad | Inhalt |
|---|---|
| `konfig/rohstoffe/palmoel.yaml` | Formular des Rohstoffs: Treiber, Kopplungen, Gegenkräfte, Preisreihe, Aktien |
| `konfig/schwellen.yaml` | alle Schwellen und Gewichte an einer Stelle (vorläufig) |
| `konfig/regionen.yaml` | Messpunkte für Regen (Ost, West) und Wind vor Sumatra |
| `konfig/quellen.yaml` | Adressen der Datenquellen |
| `konfig/handeingaben.yaml` | Werte ohne Schnittstelle, z. B. die Dipol-Vorhersage des BOM |
| `konfig/veto.yaml` | Politik-Veto: sperren, hochstufen, herabstufen |
| `konfig/veto_regeln.yaml` | Regeltabelle, nach der der Wächter Agrarrohstoffe ein Veto setzen darf |
| `konfig/kalender.yaml` | große Marktberichte (MPOB um den 10. des Monats) |
| `daten/stand.json` | alles in Zahlen, für den Wächter Agrarrohstoffe in der Cloud |
| `daten/signale.jsonl` | Logbuch: jeder Farbwechsel mit Grund und Kursen; Rot = Schattenkauf |
| `daten/preise/` | Preisarchiv je Aktie und Gegenkraft, FRED-Monatspreise |
| `daten/klima/` | Normal 1991–2020 (`regen.json`, `wind.json`) und Messarchiv |
| `abgabe/anlage-teil-N.md` | Vorlesetext im gemeinsamen Format, Rohfassung aus den Zahlen |
| `abgabe/status-anlage.md` | fünf Zeilen Status |
| `daten/geschichte/` | Geschichtsdaten für den Rückblick: Preise ab 1960, Ernte, Regen, Wind |
| `daten/rueckblick/palmoel.json` | Ergebnis des Rückblicks: Verlauf je Monat, Bilanz, Varianten |
| `daten/rueckblick/pruefzeit.json` | Buch über jedes Öffnen der Prüfzeit, mit Fingerabdruck der Regeln |
| `abgabe/rueckblick-palmoel-teil-N.md` | Vorlesetext des Rückblicks |
| `daten/nachpruefer.json`, `abgabe/nachpruefer-teil-N.md` | Nachprüfer, jeden Sonntag: Laufkontrolle aller täglichen Workflows, Stufen der Woche je Zweig, Schattendepots, Bilanz der echten Signale |
| `daten/ausstieg.json`, `abgabe/ausstieg-teil-N.md` | Ausstiegsregeln im Vergleich (sonntags nach dem Nachprüfer) |

Befehle: `python -m anlage.lauf` (täglicher Lauf), `python -m anlage.pruefen` (Prüflauf),
`python -m anlage.klimatologie` (Normal bauen), `python -m anlage.geschichte` (Geschichtsdaten),
`python -m anlage.rueckblick` (Rückblick), `python -m anlage.nachpruefer` (Nachprüfer),
`python -m anlage.metall` (Metall-Agent China), `python -m anlage.ersatz` (Ersatz-Sensoren),
`python -m anlage.ausstieg` (Ausstiegsregeln vergleichen), `python -m pytest -q` (Tests).

---

## Wie die Ampel rechnet (Palmöl)

**Checkliste.** 1 Auslöser: wirkt ein El Niño? 2 Zeitfenster: noch offen?
3 Gegenkräfte: überwiegen sie nicht? (Brent und Sojaöl, Rückgang in drei Monaten)
4 Preisprobe: schläft der Markt noch? (Z-Wert des Palmölpreises über 36 Monate unter 1)

**El-Niño-Episode:** mindestens fünf Jahreszeiten in Folge ab +0,5 (Regel der NOAA); eine
einzelne Jahreszeit knapp darunter unterbricht sie nicht. Eine gerade beginnende Folge
zählt schon vorher, außer eine frühere Episode wirkt noch nach.

**Zeitfenster** = 1 − t/T. t zählt ab dem bestätigten El-Niño-Höhepunkt (bestätigt, wenn
zwei Jahreszeiten danach niedriger lagen), T = 12 Monate beim Palmöl.

**Farbe.**
- **Grün:** kein El Niño, der noch wirkt, oder das Zeitfenster ist abgelaufen.
- **Rot:** Zeitfenster knapp (höchstens 0,5), Gegenkräfte überwiegen nicht, Markt schläft
  noch, Ostende der Kaskade bestätigt und Kreuzbestätigung West und Ost.
- **Gelb:** alles dazwischen. Der Vorlesetext sagt, was für Rot noch fehlt.
- **ohne Urteil:** Der El-Niño-Index war nie lesbar. Fällt er nur einen Tag aus, gilt der
  gespeicherte Stand; die Ampel kippt dadurch nicht.

**Zahl** hinter der Farbe: die Güte des Kandidaten, umgerechnet auf 1 bis 10, aus
w1·Stärke − w3·Z − w4·Gegenkräfte. **Vorläufig.** Das Zeitfenster steckt bewusst nicht in
der Zahl (Beschluss 26.09.2026): Die Farbe sagt, wann es so weit ist, die Zahl, wie gut der
Kandidat ist. „Rot, 9“ heißt also: jetzt, und ein guter Kandidat; „Rot, 5“: jetzt, aber mit
Vorbehalt, etwa weil der Preis schon gelaufen ist. Der Schalter dafür ist
`zahl_ohne_zeitfenster` in `konfig/schwellen.yaml`; `false` ergibt den Score wie im Konzept
(w1·Stärke + w2·Zeitfenster − w3·Z − w4·Gegenkräfte).

**Kaskade Indischer Ozean.** Stufe 1 El Niño, Stufe 2 Ostwinde vor Sumatra im Mai und
Juni (mindestens 1 m/s stärker als normal), Stufe 3 Dipol-Index ab +0,4 °C. Ostende
bestätigt = Stufe 1 und (Stufe 2 oder Stufe 3).

**Kreuzbestätigung.** Ostzeuge: Regen auf Sumatra und Borneo über 90 Tage höchstens 75 %
des Normalen. Westzeuge: kurze Regenzeit in Ostafrika (Oktober bis Dezember) mindestens
125 % des Normalen, frühestens nach 21 Tagen. Außerhalb der Saison schweigt der Westzeuge.

**Gedächtnis der Episode.** Läuft eine El-Niño-Episode, zählt für Stufe 2, Stufe 3 und die
Zeugen, ob sie *während der Episode* angeschlagen haben. Grund: Der Preisgipfel beim
Palmöl kommt Monate nach der Dürre. Wenn das Zeitfenster knapp wird, regnet es auf
Sumatra oft längst wieder normal, und der Dipol ist abgeklungen. Ohne diesen Blick
zurück wäre Rot fast nie erreichbar. Gezählt wird von 45 Tagen nach Beginn der Episode
(damit eine Dürre von vorher nicht mitzählt) bis 120 Tage nach ihrem Ende. Die Ostwinde
zählen aus dem Mai und Juni, der zwischen sechs Monaten vor Beginn und dem Höhepunkt liegt.

**Schattendepot.** Springt die Ampel ohne Veto auf Rot, gilt das im Logbuch als gedachter
Kauf zu den Kursen des Tages. Solange die Position offen ist, zählt ein erneutes Rot nicht
noch einmal. Bis der Ausstiegs-Beobachter steht, schließt erst die Rückkehr auf Grün sie.

**Politik-Veto** als letzte Schicht, aus `konfig/veto.yaml`. `hochstufen` hebt höchstens
auf Gelb; Rot kommt nur aus der Checkliste.

---

## Rückblick: die Ampel an der Geschichte prüfen

Die Zeitmaschine rechnet die Ampel für jeden Monat ab 1960 neu, jeweils zum 15. und nur
mit den Daten, die damals schon veröffentlicht waren. Es sind dieselben Module wie im
täglichen Lauf. Danach zieht die Bilanz Bilanz: Was hätte Rot gebracht?

**Einmal einrichten** (Reiter „Actions“, geht auch vom iPhone):

1. **Geschichte** → „Run workflow“. Holt Preise (Weltbank ab 1960), Ernte (USDA), Regen und
   Wind. Wegen des Tageslimits von Open-Meteo hält der erste Lauf nach gut zwei Stunden
   sauber an. **Am nächsten Tag noch einmal starten**; er macht dort weiter.
2. **Rückblick** → „Run workflow“, Häkchen „Prüfzeit öffnen“ **nicht** setzen. Dauert
   wenige Minuten. Das Ergebnis liegt als Vorlesetext in `abgabe/rueckblick-palmoel-teil-N.md`.

**Lernzeit und Prüfzeit.** Bis Ende 2015 ist Lernzeit: Hier darf man schauen und Regeln
verbessern. Die Jahre danach bleiben als Prüfzeit verschlossen, auch die Preise darin. Erst
wenn die Regeln feststehen, wird die Prüfzeit einmal geöffnet (Häkchen setzen). Jedes Öffnen
landet mit einem Fingerabdruck der Regeln in `daten/rueckblick/pruefzeit.json`; maßgeblich ist
das erste. Wer danach Regeln ändert und wieder öffnet, liest im Ergebnis „nicht mehr
unabhängig“. Wer das Ende der Lernzeit nach hinten schiebt, hat damit ebenfalls geöffnet;
auch das wird festgehalten.

**Treffer und Bestehen** (beschlossen am 26.09.2026, vor dem ersten Lauf; steht in `konfig/schwellen.yaml`):

- Treffer: Nach Rot steigt der Preis binnen zwölf Monaten um mindestens 20 %.
- Mehrwert: Zwölf Monate nach Rot liegt der Preis im Mittel mindestens 10 Prozentpunkte
  besser als über alle Monate.
- Mindestens drei Signale, nicht mehr Fehlalarme als Treffer.
- Zufallsprobe: Höchstens 10 von 100 Ziehungen gleich vieler zufälliger Monate dürfen
  genauso gut sein.

**Was der Rückblick auch zeigt:** alle großen Anstiege (mindestens 30 % binnen eines Jahres)
und ob die Ampel sie rechtzeitig, zu spät, nur mit Gelb oder gar nicht erkannt hat; woran Rot
am häufigsten scheiterte; jede El-Niño-Episode mit höchster Farbe und Preis danach; die
Zeit vor und nach 1979 getrennt (vorher sind die Wetterdaten in den Tropen unsicherer); zwei
vorher festgelegte Varianten des Zeitfensters zum Vergleich, nicht zum Aussuchen.

**Grenzen:** kein Politik-Veto und keine Handeingaben; der El-Niño-Index ist der heutige,
überarbeitete Stand; die Ostwinde gehen erst ab Juli als ganzes Jahr ein; Preise und
Gegenkräfte sind Monatsdurchschnitte; das Normal stammt aus 1991 bis 2020.

**Regel für neue Rohstoffe:** Ein neuer Rohstoff bleibt `rolle: sensor`, bis sein Rückblick
bestanden ist. Erst dann wird er `kandidat`.

---

## Metall-Agent China (Pilot Chip-Achse)

Bei Metallen treibt Politik den Preis, nicht Wetter. Der gemeinsame Nenner ist das Land:
eine Bekanntmachung des chinesischen Handelsministeriums trifft mehrere Metalle zugleich.
Der Datenlauf `python -m anlage.metall` (täglich 23:17 UTC, Workflow „Metall China“) liest
fünf maschinenlesbare Teile, die Meldungen selbst liest der Metall-Wächter in der Cloud aus
dem Gmail-Label „Metall-Meldungen“.

| Kanal | Quelle | Gelb, wenn |
|---|---|---|
| Fristen | `fristen` im Formular | eine Aussetzung ohne formelle Verlängerung in höchstens 30 Tagen ausläuft oder ausgelaufen ist |
| Gegenseite | US-Bundesregister, letzte 30 Tage | ein gewichtiger Eintrag (BIS, USTR, Präsident, Regeln des Handelsministeriums) eine Achse trifft |
| Störung: Erdbeben | USGS | Stärke 5 bis 50 km, 6 bis 150 km oder 7 bis 300 km an einem Standort |
| Störung: Starkregen | Open-Meteo, letzte 7 und nächste 7 Tage | mindestens 100 mm an einem Tag; gemessen hält 30 Tage |
| Störung: Trockenheit | ERA5, 90 Tage gegen 1991–2020 | unter 60 Prozent an den Wasserkraft-Standorten in Yunnan |

**Achsen** bündeln Metalle, die im selben chinesischen Paket kommen: Chip (Gallium,
Germanium, Antimon), Magnet (seltene Erden), Batterie (Graphit), Werkzeug (Wolfram).
Die **Wucht** (Konzentration mal Unersetzlichkeit) ordnet sie. Schlagen mehrere Kanäle
auf derselben Achse an, gilt das als bestätigt.

**Stufen:** Grün = beobachten; Gelb = ein Vorbote ist da, bereit machen, noch nicht
kaufen; Rot setzt nur der Wächter, wenn eine Verschärfung aus Peking gemeldet wird und
die **Preisprobe** zeigt, dass der Markt schläft (weniger als 15 Prozentpunkte Vorsprung
gegen XME in 20 Handelstagen).

**Ereignis-Rückblick:** Für jedes Ereignis unter `ereignisse` misst der Lauf, wie die Werte
0, 5, 20 und 60 Handelstage danach gegen XME lagen, dazu die 20 Tage davor. Vorläufige
Prüfregel für den Schritt vom Sensor zum Kandidaten: mindestens drei Verschärfungen auf
der eigenen Achse, in mindestens der Hälfte ein Vorsprung von 10 Prozentpunkten. Für die
Magnet-Achse reichen die Ereignisse bis 2010 zurück (Quotenkürzungen, Lieferstopp nach Japan,
WTO-Verfahren, Abschaffung der Quoten und Zölle 2015), damit Lynas an mehr Fällen geprüft wird.

**Pflege:** Verlängert Peking eine Aussetzung formell, das neue Datum unter
`verlaengert_bis` eintragen. Neue Ereignisse unter `ereignisse` ergänzen (Datum der
Ankündigung). Ein neues Land: `konfig/metalle/china.yaml` kopieren und `--land` setzen.

| Pfad | Inhalt |
|---|---|
| `konfig/metalle/china.yaml` | Formular: Metalle, Achsen, Werte, Standorte, Fristen, Ereignisse |
| `daten/metall/china/stand.json` | Stufen je Achse mit Gründen, alle Kanäle, Preisprobe, Rückblick in Kürze |
| `daten/metall/china/rueckblick.json` | jeder Fall des Rückblicks einzeln |
| `daten/metall/china/stoerungen.json` | Protokoll gemessener Starkregen (hält die Achse 30 Tage auf Gelb) |
| `daten/metall/china/klima/`, `kurse/` | Regen-Normal der Wasserkraft-Standorte, Kursarchiv |
| `abgabe/metall-china-teil-N.md`, `abgabe/status-metall-china.md` | Vorlesetext und Status |

---

## Ersatz-Sensoren

Grundsatz für alle: Der Sensor schlägt beim Original aus, gekauft wird der handelbare Ersatz.
Ein Workflow „Ersatz-Sensoren“ (täglich 02:07 UTC) rechnet jedes Formular unter `konfig/ersatz/`
(`python -m anlage.ersatz --kennung alle`). Jeder Sensor führt ein Schattendepot
(`daten/ersatz/<kennung>/schattendepot.json`: Rot kauft den Ersatz gedacht) und einen Verlauf der
Stufen für den Nachprüfer (`verlauf.jsonl`).

### Haselnuss → Select Harvests

Grundsatz: Der Sensor schlägt beim Original aus, gekauft wird der handelbare Ersatz. Haselnuss
ist nicht handelbar; wird sie knapp, weichen die Hersteller auf Mandeln aus. Select Harvests
(SHV.AX) ist der einzige reine Mandel-Wert, Vergleichsmaßstab ist der ASX 200.

- **Sensor:** Spätfrost an fünf Anbauorten der Schwarzmeerküste (Ordu, Giresun, Trabzon, Samsun,
  Düzce), ERA5-Tagesminimum auf die Höhe der Obstgärten umgerechnet. Frostnacht: mindestens zwei
  Orte bei −1 °C oder kälter; stark ab −3 °C. Saison 10. März bis 30. April, Vorhersagen zählen
  14 Tage vorher.
- **Stufe:** Gelb bei vorhergesagtem oder gemessenem Frost und nach einem Frostjahr bis
  30. September; Rot nur bei gemessenem starkem Frost, bestandenem Rückblick und schlafendem Markt.
- **Rückblick:** alle Frostsaisons ab 1991, abgeglichen mit den belegten Frostjahren 2004, 2014 und
  2025; danach, wie Select Harvests 20, 60 und 120 Handelstage nach der ersten Frostnacht gegen den
  ASX 200 lief.
- Formular `konfig/ersatz/haselnuss.yaml`; schreibt `daten/ersatz/haselnuss/` und
  `abgabe/ersatz-haselnuss-teil-N.md`. Die Frostsaisons werden je Saison für alle fünf Orte in
  einem Abruf geladen (das Archiv antwortet von GitHub aus oft langsam).
- **Schattendepot:** geschlossen am Ende der Ernte (30. September), bis eine andere Ausstiegsregel gilt.

### Palladium → Platin

Beide Metalle sitzen im Autokatalysator und sind dort austauschbar. Wird Palladium zu teuer
(etwa weil Lieferungen aus Russland ausfallen), stellen die Hersteller auf Platin um. Hier sind
beide handelbar; der Sensor ist der Preis des Originals (Terminkontrakte PA=F und PL=F, Dollar je
Unze), gekauft würde der Platin-ETF PPLT, Vergleichsmaßstab ist der Gold-ETF GLD. Die bereinigten ETF-Kurse
taugen nicht für das Verhältnis: Ihr Verhältnis liegt etwa beim Doppelten des Metallverhältnisses.

- **Signal:** Palladium steigt binnen 60 Handelstagen um mindestens 30 Prozent (Sprung), oder es
  wird teurer als Platin (Verhältnis der Preise je Unze über 1). Nach einem Signal zählt das nächste
  erst nach 120 Handelstagen.
- **Stufe:** Gelb 180 Tage nach einem Signal und solange Palladium teurer ist als Platin; Rot nur bei
  einem höchstens 30 Tage alten Signal, bestandenem Rückblick und schlafendem Markt.
- **Rückblick:** Platin-ETF gegen Gold 20, 60, 120 und 250 Handelstage nach jedem Signal seit 2010;
  geurteilt wird nach 120.
- Formular `konfig/ersatz/palladium.yaml`; Schattendepot schließt nach 180 Tagen.

## Ausstiegsregeln

`python -m anlage.ausstieg` (sonntags im Workflow „Nachprüfer“) vergleicht an denselben Fällen wie
die Rückblicke, wann man jeweils wieder ausgestiegen wäre: die bisherige Regel, eine feste
Haltedauer, ein Gewinnziel, eine nachgezogene Grenze unter dem Höchststand und eine Verbindung aus
Verlustgrenze und nachgezogener Grenze. Die Varianten stehen vorher fest in `konfig/ausstieg.yaml`
und werden nicht nach dem Ergebnis nachgestellt. Verglichen werden nur Fälle, die unter allen
Regeln abgeschlossen sind. Welche Regel gilt (`gilt:`), legt Raphael fest; bis dahin gilt überall
die bisherige, und erst danach wird sie in die Schattendepots eingebaut. Palmöl rechnet nur mit den
Signalen der Lernzeit, die Prüfzeit bleibt verschlossen.

---

## Pflegen und erweitern

**Handeingabe ändern** (auch vom iPhone): auf GitHub die Datei öffnen, Stift-Symbol,
ändern, „Commit changes“. Beispiel `konfig/handeingaben.yaml`:

```yaml
bom_iod_prognose:
  stand: 2026-09-23
  aussage: "positiver Dipol bis November erwartet"
  richtung: positiv
```

Nach 21 Tagen meldet der Überblick die Eingabe als veraltet.

**Veto eintragen** in `konfig/veto.yaml`:

```yaml
aktiv:
  - rohstoff: palmoel
    wirkung: sperren          # sperren | hochstufen | herabstufen
    grund: "Indonesien ändert die Exportabgabe"
    seit: 2026-10-02
    bis: 2026-11-02
```

**Neuer Rohstoff:** `konfig/rohstoffe/palmoel.yaml` kopieren, umbenennen, ausfüllen. Mit
`treiber: klima` und `ausloeser: enso` rechnet er sofort mit. Für `politik` und `struktur`
(Metalle, Spannungspegel) steht im Überblick „Rechenweg noch nicht gebaut“. Die Tests
prüfen bei jedem Hochladen, ob das Formular vollständig ist; ein Tippfehler fällt so
sofort auf. Neue Gegenkräfte brauchen einen Ticker in `konfig/quellen.yaml`.

**Neuer Messpunkt:** in `konfig/regionen.yaml` ergänzen und den Workflow „Klimatologie“
noch einmal starten. Er holt nur den neuen Punkt.

**Schwellen ändern:** nur in `konfig/schwellen.yaml`. Später schlägt der Nachprüfer
Änderungen vor; entschieden wird von Hand.

---

## Grenzen

- **Yahoo Finance** ist keine offizielle Schnittstelle und bremst GitHub-Rechner manchmal
  aus. Fällt sie aus, rechnet der Lauf mit dem Preisarchiv weiter und meldet das. Fehlt
  beim allerersten Lauf noch jedes Archiv, sind die Gegenkräfte unbekannt und Rot ist an
  diesem Tag nicht möglich. Der laufende Handelstag wird nie mitgerechnet.
- **Datumsangaben** in Handeingaben und Veto als JJJJ-MM-TT eintragen. Ein Tippfehler stoppt
  den Lauf nicht, der Eintrag bleibt dann aber unberücksichtigt und der Überblick meldet es.
- **ERA5 (Open-Meteo)** liegt etwa fünf Tage zurück. Der Regen „der letzten 90 Tage“
  endet also rund eine Woche vor heute.
- **Monatswerte:** El-Niño-Index, Dipol-Index und Palmölpreis (FRED) kommen einmal im
  Monat, mit etwa einem Monat Verzug.
- **Normalwerte** stammen aus demselben Modell (ERA5) wie die heutigen Werte. Das hält den
  Vergleich fair, ersetzt aber keine Stationsmessung.
- **Die Testszenarien sind erfunden** und prüfen nur die Rechenwege, nicht die Treffsicherheit.
  Die Treffsicherheit prüft der Rückblick.
