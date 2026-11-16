from datetime import date, timedelta

import pytest

import check
import config
import hdc
import pages
import periods
from app import app

P = periods.make(2569)


def row(rows, item_contains):
    return next(r for r in rows if item_contains in r["item"])


def test_is_lan():
    assert check.is_lan("192.168.11.5") and check.is_lan("127.0.0.1") and check.is_lan("::1") and check.is_lan("10.1.2.3")
    assert not check.is_lan("8.8.8.8") and not check.is_lan("") and not check.is_lan("abc")


def test_request_allowed_requires_all_forwarded_addresses_private():
    ok = check.request_allowed("127.0.0.1", {"X-Forwarded-For": "192.168.11.5"})
    bad = check.request_allowed("127.0.0.1", {"X-Forwarded-For": "8.8.8.8, 192.168.11.5"})
    cf = check.request_allowed("127.0.0.1", {"CF-Connecting-IP": "8.8.8.8"})
    assert ok and not bad and not cf
    assert not check.request_allowed("8.8.8.8", {})


def _clinic_rows(fake_db, name="โรคความดัน", n=10):
    fake_db.add("from clinic c", [{"clinic": "002", "name": name}] if name else [])
    fake_db.add("count(distinct m.hn)", [{"n": n}])


def test_clinic_row_ok(fake_db):
    _clinic_rows(fake_db)
    r = row(check.audit(P), "คลินิก HT")
    assert r["status"] == "ok" and "002" in r["app_uses"] and "โรคความดัน" in r["found"] and r["env_hint"] == "NCD_CLINIC_HT"


def test_clinic_missing_code_is_error(fake_db):
    _clinic_rows(fake_db, name=None, n=0)
    assert row(check.audit(P), "คลินิก HT")["status"] == "error"


def test_clinic_without_members_is_warn(fake_db):
    _clinic_rows(fake_db, n=0)
    assert row(check.audit(P), "คลินิก HT")["status"] == "warn"


def test_lab_status_levels(fake_db):
    fake_db.add("from lab_items", [{"lab_items_code": 271, "lab_items_name": "HbA1C"}])
    fake_db.add("count(distinct h.hn)", [{"n": 0}])
    r = row(check.audit(P), "HbA1c")
    assert r["status"] == "warn" and "HbA1C" in r["found"]
    fake_db.responses.clear()
    fake_db.add("from lab_items", [{"lab_items_code": 271, "lab_items_name": "HbA1C"}])
    fake_db.add("count(distinct h.hn)", [{"n": 120}])
    assert row(check.audit(P), "HbA1c")["status"] == "ok"
    fake_db.responses.clear()
    assert row(check.audit(P), "HbA1c")["status"] == "error"          # ไม่พบรหัส lab นี้เลย


def test_unconfigured_list_is_warn_not_crash(fake_db, monkeypatch):
    monkeypatch.setattr(config, "LAB_LDL", [])
    r = row(check.audit(P), "LDL")
    assert r["status"] == "warn" and "ไม่ได้ตั้งค่า" in r["found"]


def test_icd_zero_patients_warns_with_hint(fake_db):
    r = row(check.audit(P), "ICD-10 Stroke")
    assert r["status"] == "warn" and r["env_hint"] == "NCD_ICD_STROKE"


def test_icd_found_ok(fake_db):
    fake_db.add("ovstdiag", [{"hn": "1"}, {"hn": "2"}])
    assert row(check.audit(P), "ICD-10 Stroke")["status"] == "ok"


def test_one_failing_section_isolated(fake_db):
    _clinic_rows(fake_db)
    fake_db.responses.insert(0, ("from lab_items", RuntimeError("db down")))
    rows = check.audit(P)
    assert any(r["status"] == "error" and "ตรวจไม่สำเร็จ" in r["found"] for r in rows)
    assert row(rows, "คลินิก HT")["status"] == "ok"


def test_rows_contain_only_counts_no_patient_identifiers(fake_db):
    fake_db.add("ovstdiag", [{"hn": "0000123"}])
    text = str(check.audit(P))
    assert "0000123" not in text


def test_latest_visit_warns_when_stale(fake_db):
    fake_db.add("max(vstdate)", [{"d": date.today() - timedelta(days=60)}])
    assert row(check.audit(P), "visit ล่าสุด")["status"] == "warn"
    fake_db.responses.clear()
    fake_db.add("max(vstdate)", [{"d": date.today()}])
    assert row(check.audit(P), "visit ล่าสุด")["status"] == "ok"


def test_hdc_row_reports_cache(fake_db, monkeypatch):
    monkeypatch.setattr(hdc, "_load", lambda: {"s_ht_control|2569": {"fetched_at": "2026-11-04T10:00:00"}})
    r = row(check.audit(P), "HDC")
    assert r["status"] == "ok" and "4 พ.ย. 2569" in r["found"]
    monkeypatch.setattr(hdc, "_load", lambda: {})
    assert row(check.audit(P), "HDC")["status"] == "warn"


def test_summary_counts():
    rows = [{"status": "ok"}, {"status": "ok"}, {"status": "warn"}, {"status": "error"}]
    assert check.summary(rows) == {"ok": 2, "warn": 1, "error": 1}


def test_data_audited_reads_env(monkeypatch):
    monkeypatch.delenv("NCD_DATA_AUDITED", raising=False)
    assert check.data_audited() is False
    monkeypatch.setenv("NCD_DATA_AUDITED", "1")
    assert check.data_audited() is True


def test_check_route_blocks_non_lan(fake_db):
    c = app.test_client()
    assert c.get("/check", environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403
    assert c.get("/check", environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 403


def test_check_route_shows_audit_table(fake_db):
    _clinic_rows(fake_db)
    r = app.test_client().get("/check", environ_base={"REMOTE_ADDR": "192.168.11.5"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "แอปใช้" in html and "พบในข้อมูล" in html and "NCD_CLINIC_HT" in html
    assert "<th>hn</th>" not in html.lower()


@pytest.fixture
def fake_page(monkeypatch):
    monkeypatch.setitem(pages.REGISTRY, "ht", lambda p, src="hosxp", opts=None: {"title": "ทดสอบ", "kpis": []})


def test_banner_shown_until_audited(fake_page, monkeypatch):
    monkeypatch.delenv("NCD_DATA_AUDITED", raising=False)
    html = app.test_client().get("/ht").get_data(as_text=True)
    assert "ตัวเลขยังไม่ได้ตรวจกับข้อมูลของโรงพยาบาลนี้" in html and "/check" in html


def test_banner_hidden_when_env_set(fake_page, monkeypatch):
    monkeypatch.setenv("NCD_DATA_AUDITED", "1")
    assert "ตัวเลขยังไม่ได้ตรวจ" not in app.test_client().get("/ht").get_data(as_text=True)


def test_banner_not_in_print_mode(fake_page, monkeypatch):
    monkeypatch.delenv("NCD_DATA_AUDITED", raising=False)
    assert "ตัวเลขยังไม่ได้ตรวจ" not in app.test_client().get("/ht?print=1").get_data(as_text=True)
