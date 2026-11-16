"""คีย์แคชของหน้าสาธารณะต้องมีจำนวนจำกัด — query string แปลก ๆ ต้องไม่ทำให้ยิงฐานซ้ำหรือไล่หน้าที่อุ่นไว้ออก"""
from datetime import date

import pytest

import pages
import periods
from app import app


@pytest.fixture
def client():
    return app.test_client()


def _count_builds(monkeypatch):
    calls = []

    def fake(p, src="hosxp", opts=None):
        calls.append(dict(opts or {}))
        return {"title": "HT", "kpis": []}
    monkeypatch.setitem(pages.REGISTRY, "ht", fake)
    monkeypatch.setitem(pages.REGISTRY, "copd", fake)
    return calls


def test_unknown_args_share_one_cache_entry(client, monkeypatch):
    calls = _count_builds(monkeypatch)
    for i in range(20):
        assert client.get(f"/ht?x={i}&utm_source=a{i}").status_code == 200
        assert client.get(f"/api/ht.json?junk={'A' * 500}{i}").status_code == 200
    assert len(calls) == 1                         # สร้างครั้งเดียว ที่เหลือมาจากแคช
    assert calls[0] == {}                          # ตัวเลือกที่หน้าไม่ใช้ไม่ถูกส่งต่อ


def test_lock_table_does_not_grow_with_junk_args(client, monkeypatch):
    _count_builds(monkeypatch)
    monkeypatch.setattr(pages, "_locks", {})
    for i in range(50):
        client.get(f"/ht?z={i}")
    assert len(pages._locks) <= 1


def test_warmed_page_not_evicted_by_junk(client, monkeypatch):
    calls = _count_builds(monkeypatch)
    client.get("/ht")
    for i in range(100):
        client.get(f"/ht?x={i}")
    client.get("/ht")
    assert len(calls) == 1


def test_copd_grp_allowlisted(client, monkeypatch):
    calls = _count_builds(monkeypatch)
    for g in ("copd", "asthma", "all", "junk1", "junk2", ""):
        client.get(f"/copd?grp={g}")
    # copd, asthma, และค่าเริ่มต้น (all / ค่าแปลก ๆ รวมเป็นคีย์เดียว)
    assert sorted(map(lambda o: o.get("grp", "all"), calls)) == ["all", "asthma", "copd"]


def test_clean_opts():
    assert pages.clean_opts("copd", {"grp": "copd", "x": "1"}) == {"grp": "copd"}
    assert pages.clean_opts("copd", {"grp": "<script>"}) == {}
    assert pages.clean_opts("ht", {"grp": "copd", "fy": "2569"}) == {}
    assert pages.clean_opts("ht", None) == {}


def test_scope_canonical_and_non_ascii_digits():
    today = date(2026, 11, 16)
    assert periods.parse({"scope": "m01"}, today).scope == "m1"
    assert periods.parse({"scope": "m001"}, today).scope == "m1"
    assert periods.parse({"scope": "m²"}, today).scope == "year"     # เลขยก: เดิม 500
    assert periods.parse({"fy": "²²"}, today).fy == periods.fiscal_year(today)
    assert periods.parse({"fy": "๒๕๖๙"}, today).fy == periods.fiscal_year(today)


def test_non_ascii_digit_params_do_not_500(client, monkeypatch):
    _count_builds(monkeypatch)
    assert client.get("/ht?fy=%C2%B2&scope=m%C2%B2").status_code == 200
