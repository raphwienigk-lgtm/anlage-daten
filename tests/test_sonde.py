"""Quellen-Sonde: jede Probe schreibt ihre Datei, Fehler bleiben einzeln."""
from __future__ import annotations

from anlage import sonde, speicher


def test_sonde_schreibt_und_faengt_fehler(ablage, monkeypatch, tmp_path):
    monkeypatch.setattr(sonde, "ORDNER", tmp_path / "sonde")

    def gut():
        return "URL: x\nStatus: 200"

    def schlecht():
        raise ValueError("kaputt")

    monkeypatch.setattr(sonde, "PROBEN", {"gut": gut, "schlecht": schlecht})
    assert sonde.main([]) == 0
    assert (tmp_path / "sonde" / "gut.txt").read_text(encoding="utf-8").startswith("URL: x")
    assert "ValueError: kaputt" in (tmp_path / "sonde" / "schlecht.txt").read_text(encoding="utf-8")
    ue = speicher.lies_json(tmp_path / "sonde" / "uebersicht.json")
    assert ue["gut"]["status"] == "ok" and ue["schlecht"]["status"] == "Fehler"
