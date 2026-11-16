import json
from datetime import datetime, timedelta

import pytest

import hdc


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    p = tmp_path / "hdc_cache.json"
    monkeypatch.setattr(hdc, "CACHE_PATH", str(p))
    return p


def rows_payload(rows):
    return {"data": rows, "total": len(rows)}


def row(hosp, area, target, result, proc="202611040310", **kw):
    d = {"hospcode": hosp, "areacode": area, "target": target, "result": result,
         "date_com": proc, "id": 1, "b_year": "2569", "age_group": None, "groupcode": None,
         "groupname": None, "yymm": None}
    d.update(kw)
    return d


def old_cache(path, hours_old):
    when = (datetime.now() - timedelta(hours=hours_old)).isoformat(timespec="seconds")
    path.write_text(json.dumps({"s_dm_control|2569": {
        "fetched_at": when, "totals": {"target": 100.0, "result": 40.0},
        "by_unit": {"07001": {"target": 100.0, "result": 40.0}}}}), encoding="utf-8")
    return when


def test_totals_only_for_district_rows(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", lambda body, tries=5, **kw: rows_payload([
        row("07001", "302501", 60, 20), row("07002", "302502", 40, 10),
        row("99999", "309901", 500, 500)]))               # นอกอำเภอ 3025
    r = hdc.fetch_table("s_dm_control", 2569)
    assert r.totals == {"target": 100.0, "result": 30.0}
    assert set(r.by_unit) == {"07001", "07002"} and r.by_unit["07002"]["result"] == 10.0
    assert r.stale is False and r.error is None and r.fetched_at


def test_duplicate_runs_keep_latest_date_com(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", lambda body, tries=5, **kw: rows_payload([
        row("07001", "302501", 60, 20, proc="202611010000"),
        row("07001", "302501", 70, 25, proc="202611040000")]))
    assert hdc.fetch_table("s_dm_control", 2569).totals == {"target": 70.0, "result": 25.0}


def test_fresh_cache_does_not_call_api(cache_path, monkeypatch):
    old_cache(cache_path, hours_old=1)
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: pytest.fail("ไม่ควรเรียก API"))
    r = hdc.fetch_table("s_dm_control", 2569)
    assert r.totals["target"] == 100.0 and r.stale is False


def test_api_down_with_cache_returns_stale(cache_path, monkeypatch):
    when = old_cache(cache_path, hours_old=48)

    def boom(*a, **k):
        raise RuntimeError("429")

    monkeypatch.setattr(hdc, "_post", boom)
    r = hdc.fetch_table("s_dm_control", 2569)
    assert r.stale is True and r.fetched_at == when and r.totals["result"] == 40.0
    assert r.error is None


def test_api_down_without_cache_reports_error(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    r = hdc.fetch_table("s_dm_control", 2569)
    assert r.error and r.totals == {} and r.by_unit == {}


def test_bad_json_never_overwrites_cache(cache_path, monkeypatch):
    old_cache(cache_path, hours_old=48)
    before = cache_path.read_text(encoding="utf-8")
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: {"unexpected": 1})
    r = hdc.fetch_table("s_dm_control", 2569)
    assert r.stale is True and r.totals["target"] == 100.0
    assert cache_path.read_text(encoding="utf-8") == before


def test_no_district_rows_never_overwrites_cache(cache_path, monkeypatch):
    old_cache(cache_path, hours_old=48)
    before = cache_path.read_text(encoding="utf-8")
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: rows_payload([row("99999", "309901", 1, 1)]))
    r = hdc.fetch_table("s_dm_control", 2569)
    assert r.stale is True and cache_path.read_text(encoding="utf-8") == before


def test_successful_fetch_is_cached(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", lambda body, tries=5, **kw: rows_payload([row("07001", "302501", 60, 20)]))
    hdc.fetch_table("s_dm_control", 2569)
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["s_dm_control|2569"]["totals"]["target"] == 60.0


def test_hospcode_filter(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", lambda body, tries=5, **kw: rows_payload([
        row("07001", "302501", 60, 20), row("07002", "302502", 40, 10)]))
    r = hdc.fetch_table("s_dm_control", 2569, hospcode="07002")
    assert r.totals == {"target": 40.0, "result": 10.0}
