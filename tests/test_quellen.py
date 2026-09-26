"""Einlesen der Quellenformate."""
from datetime import date

import pytest

from anlage.netz import AbrufFehler
from anlage.quellen import klimaindizes, kurse, openmeteo
from conftest import BEISPIEL


def test_oni_liest_jahreszeiten_und_monate():
    reihe = klimaindizes.lies_oni((BEISPIEL / "oni_ausschnitt.txt").read_text())
    assert len(reihe) == 18
    assert reihe[0] == {"jahreszeit": "DJF", "jahr": 2023, "monat": 1, "wert": -0.68}
    assert reihe[11]["jahreszeit"] == "NDJ" and reihe[11]["monat"] == 12
    assert reihe[-1]["wert"] == 0.08


def test_oni_ohne_werte_ist_fehler():
    with pytest.raises(AbrufFehler):
        klimaindizes.lies_oni("<html>Wartung</html>")


@pytest.mark.parametrize("datei", ["dmi_jma_ausschnitt.txt", "dmi_psl_ausschnitt.txt"])
def test_dmi_beide_formate_ueberspringen_fehlwerte(datei):
    reihe = klimaindizes.lies_monatsreihe((BEISPIEL / datei).read_text())
    assert len(reihe) == 22                      # 12 + 10, zwei Fehlwerte übersprungen
    assert reihe[9] == {"jahr": 2023, "monat": 10, "wert": 1.25}
    assert reihe[-1] == {"jahr": 2024, "monat": 10, "wert": -0.3}


def test_dmi_nimmt_zweite_quelle_wenn_erste_ausfaellt(monkeypatch):
    from anlage import netz

    def falsch(url, params=None):
        if "erste" in url:
            raise AbrufFehler("Fehler 404")
        return (BEISPIEL / "dmi_psl_ausschnitt.txt").read_text()
    monkeypatch.setattr(netz, "hole_text", falsch)
    reihe, name = klimaindizes.hole_dmi([{"name": "A", "url": "http://erste"}, {"name": "B", "url": "http://zweite"}])
    assert name == "B" and reihe[-1]["wert"] == -0.3


def test_fred_ueberspringt_punkte():
    reihe = kurse.lies_fred_csv((BEISPIEL / "fred_ausschnitt.csv").read_text())
    assert [e["datum"] for e in reihe] == ["2024-01-01", "2024-02-01", "2024-04-01"]
    assert reihe[-1]["wert"] == 951.0


def test_openmeteo_gewicht_und_zonalwind():
    assert openmeteo.gewicht(10) == 1.0
    assert openmeteo.gewicht(365) == pytest.approx(26.07, abs=0.01)
    assert openmeteo.gewicht(61, 2) == pytest.approx(4.357, abs=0.01)
    assert openmeteo.zonalwind(5.0, 90) == pytest.approx(-5.0)      # Wind aus Osten
    assert openmeteo.zonalwind(5.0, 270) == pytest.approx(5.0)      # Wind aus Westen
    assert openmeteo.zonalwind(5.0, 0) == pytest.approx(0.0, abs=1e-9)


def test_openmeteo_meldet_fehler_der_quelle(monkeypatch):
    from anlage import netz
    monkeypatch.setattr(netz, "hole_json", lambda url, params=None: {"error": True, "reason": "end_date out of range"})
    with pytest.raises(AbrufFehler, match="out of range"):
        openmeteo.hole_tage("http://x", {"name": "P", "lat": 0, "lon": 0}, date(2026, 1, 1), date(2026, 1, 2))


def test_preisarchiv_fuehrt_zusammen(tmp_path):
    pfad = kurse.archiv_pfad(tmp_path, "F34.SI")
    assert pfad.name == "F34_SI.csv"
    kurse.ergaenze_archiv(pfad, [{"datum": "2026-09-01", "schluss": 3.1, "volumen": 10},
                                 {"datum": "2026-09-02", "schluss": 3.2, "volumen": None}])
    reihe = kurse.ergaenze_archiv(pfad, [{"datum": "2026-09-02", "schluss": 3.25, "volumen": 12},
                                         {"datum": "2026-09-03", "schluss": 3.3, "volumen": 11}])
    assert [e["schluss"] for e in reihe] == [3.1, 3.25, 3.3]
    assert kurse.lies_archiv(pfad)[1]["volumen"] == 12


def test_openmeteo_kuerzt_enddatum_auf_erlaubte_spanne(monkeypatch):
    from anlage import netz
    gesehen = []

    def falsch(url, params=None):
        gesehen.append(params["end_date"])
        if params["end_date"] > "2026-09-21":
            raise AbrufFehler("Fehler 400 bei x: {\"error\":true,\"reason\":\"Parameter 'end_date' is out of "
                              "allowed range from 1940-01-01 to 2026-09-21\"}")
        return {"daily": {"time": ["2026-09-20", "2026-09-21"], "precipitation_sum": [1.0, 2.0]}}
    monkeypatch.setattr(netz, "hole_json", falsch)
    werte = openmeteo.hole_tage("http://x", {"name": "P", "lat": 0, "lon": 0}, date(2026, 9, 20), date(2026, 9, 24))
    assert gesehen == ["2026-09-24", "2026-09-21"] and werte == {"2026-09-20": 1.0, "2026-09-21": 2.0}


def test_veto_regeln_sind_vollstaendig():
    from anlage import konfig
    daten = konfig.lade_yaml(konfig.KONFIG / "veto_regeln.yaml")
    rohstoffe = set(konfig.konfiguration()["rohstoffe"])
    ids = [r["id"] for r in daten["regeln"]]
    assert len(ids) == len(set(ids))
    for r in daten["regeln"]:
        assert r["rohstoff"] in rohstoffe, r
        assert r["wirkung"] in ("sperren", "hochstufen", "herabstufen", "beendet"), r
        assert r.get("ausloeser"), r
        if r["wirkung"] == "beendet":
            assert r["beendet"] in ids, r
        else:
            assert isinstance(r["dauer_tage"], int) and r["dauer_tage"] > 0, r
