"""Metall-Agent: politisches Frühwarnsystem für Metalle, zuerst China (Pilot Chip-Achse).

Bei Metallen treibt Politik den Preis. Der Datenteil hier holt nur, was sich maschinell
lesen lässt: Fristen aus dem Formular, das US-Bundesregister (Gegenseite), Erdbeben,
Starkregen und Trockenheit an Förder- und Hüttenstandorten (Störung), Kurse der
handelbaren Werte (Preisprobe) und den Ereignis-Rückblick. Die Meldungen aus Peking
(Ausfuhr, Reserve, Fünfjahresplan) liest der Metall-Wächter in der Cloud aus Gmail.
Rot setzt nur er.

Aufruf: python -m anlage.metall [--land china] [--budget-minuten 25]
"""
