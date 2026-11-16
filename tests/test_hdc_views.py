import pytest

import hdc
import periods
from queries import hdc_views

P = periods.make(2569)


def result(totals=None, by_unit=None, stale=False, fetched_at="2026-11-04T10:00:00", error=None):
    return hdc.HdcResult(totals=totals or {}, by_unit=by_unit or {}, fetched_at=fetched_at, stale=stale, error=error)


@pytest.fixture
def fake_hdc(monkeypatch, fake_db):
    tables = {
        "s_ht_control": result({"target": 5911.0, "bp": 4120.0, "result": 3219.0},
                               {"07001": {"target": 3000.0, "bp": 2000.0, "result": 1500.0},
                                "07002": {"target": 2911.0, "bp": 2120.0, "result": 1719.0}}),
        "s_ht_screen": result({"target": 14845.0, "result": 12712.0}),
        "s_ht_incidence": result({"result": 659.0, "result10": 78.0, "result11": 71.0, "result12": 68.0,
                                  "result01": 54.0, "result02": 56.0, "result03": 61.0, "result04": 51.0,
                                  "result05": 36.0, "result06": 54.0, "result07": 43.0, "result08": 54.0,
                                  "result09": 33.0}),
        "s_ht_pop_age": result({f"result_group{i}": v for i, v in zip(range(1, 6), (6, 195, 574, 1286, 3850))}),
    }
    calls = []

    def get(table, fy, hospcode=None, refresh=False):
        calls.append((table, fy))
        return tables.get(table, result(error="HDC ไม่มีข้อมูล"))

    monkeypatch.setattr(hdc, "get", get)
    fake_db.add("from hospcode", [{"hospcode": "07001", "name": "รพ.สต.ก"}, {"hospcode": "07002", "name": "รพ.สต.ข"}])
    return tables, calls


def test_ht_control_percentage_uses_bp_as_denominator(fake_hdc):
    d = hdc_views.build_ht(P)
    pct = round(100 * 3219 / 4120, 1)
    assert d["donut"]["center"] == f"{pct:.1f}%"
    assert [v for _, v, _ in d["donut"]["parts"]] == [3219, 4120 - 3219]
    assert any(f"{pct:.1f}%" in k["sub"] or f"{pct:.1f}%" in k["value"] for k in d["kpis"])


def test_unit_comparison_sorted_by_rate_with_names(fake_hdc):
    d = hdc_views.build_ht(P)
    rows = d["table"]["rows"]
    assert rows[0][0] == "รพ.สต.ข"                  # 1719/2120 = 81.1% > 1500/2000 = 75%
    assert rows[1][0] == "รพ.สต.ก"


def test_monthly_incidence_in_fiscal_order(fake_hdc):
    d = hdc_views.build_ht(P)
    assert d["monthly"]["series"][0]["values"][:3] == [78, 71, 68]
    assert len(d["monthly"]["labels"]) == 12 and sum(d["monthly"]["series"][0]["values"]) == 659


def test_stale_cache_adds_warning_with_date(fake_hdc):
    tables, _ = fake_hdc
    tables["s_ht_control"] = result(tables["s_ht_control"].totals, tables["s_ht_control"].by_unit, stale=True)
    d = hdc_views.build_ht(P)
    assert any(n["tone"] == "warn" and "4 พ.ย. 2569" in n["text"] for n in d["notes"])


def test_missing_table_isolated(fake_hdc):
    tables, _ = fake_hdc
    tables["s_ht_screen"] = result(error="HDC s_ht_screen: ดึงข้อมูลไม่ได้")
    d = hdc_views.build_ht(P)
    assert d["kpis"] and "error" not in d["donut"]          # ส่วนอื่นยังอยู่


def test_no_cache_no_data_degrades_to_errors(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", lambda *a, **k: result(error="HDC: ดึงข้อมูลไม่ได้"))
    d = hdc_views.build_ht(P)
    assert "error" in d["donut"] and "error" in d["table"]


def test_non_year_scope_note(fake_hdc):
    d = hdc_views.build_ht(periods.make(2569, "q1"))
    assert any("ทั้งปีงบ" in n["text"] for n in d["notes"])


def test_explains_definition_difference(fake_hdc):
    d = hdc_views.build_ht(P)
    assert any("ไม่ควรนำ" in n["text"] or "ต่างจาก" in n["text"] for n in d["notes"])


def test_dm_hdc_never_shows_control_rate(monkeypatch, fake_db):
    tables = {"s_dm_screen": result({"target": 17644.0, "result": 14769.0}, {"07001": {"target": 100.0, "result": 90.0}}),
              "s_dm_incidence": result({"result": 230.0}), "s_dm_pop_age": result({"result_group5": 1612.0}),
              "s_dm_retina_kpi": result({"target": 2663.0, "result": 23.0})}
    monkeypatch.setattr(hdc, "get", lambda t, fy, hospcode=None, refresh=False: tables.get(t, result(error="x")))
    fake_db.add("from hospcode", [{"hospcode": "07001", "name": "รพ.สต.ก"}])
    d = hdc_views.build_dm(P)
    text = str(d)
    assert "ควบคุมได้" not in str(d["kpis"]) and "donut" not in d
    assert d["table"]["rows"][0][0] == "รพ.สต.ก" and d["table"]["rows"][0][3] == "90.0%"
    assert any("HbA1c" in n["text"] for n in d["notes"]) and text
