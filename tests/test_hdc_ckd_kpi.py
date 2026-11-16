"""ตัวชี้วัดคลินิก CKD ฝั่ง HDC (ตาราง s_kpi_ckd_* ระดับ รพ. + CKD รายใหม่รายหน่วยบริการ)"""
import config
import hdc
import periods
from queries import hdc_views

P = periods.make(2569)


def fake_get(errors=()):
    def get(table, fy, hospcode=None, refresh=False):
        if table in errors:
            return hdc.HdcResult(error="ดึงไม่ได้")
        if table == "s_kpi_ckd_incidence":
            return hdc.HdcResult(totals={"target": 500.0, "result": 45.0},
                                 by_unit={"10894": {"result": 33.0}, "02840": {"result": 12.0}},
                                 fetched_at="2026-11-14T10:00:00")
        return hdc.HdcResult(totals={"target": 100.0, "result": 70.0}, by_unit={"10894": {"target": 100.0, "result": 70.0}},
                             fetched_at="2026-11-14T10:00:00")
    return get


def _kpi_table(d):
    return next(x for x in d["extra"] if x.get("title", "").startswith("ตัวชี้วัดคลินิก CKD"))


def test_new_tables_are_synced_daily():
    for t, *_ in hdc_views.HDC_CKD_KPIS:
        assert t in hdc.TABLES
    assert "s_kpi_ckd_incidence" in hdc.TABLES


def test_hdc_ckd_page_has_clinic_kpi_table(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get())
    monkeypatch.setattr(config, "TARGET_CKD_EGFR", 66.0)
    t = _kpi_table(hdc_views.build_ckd(P))
    assert len(t["rows"]) == len(hdc_views.HDC_CKD_KPIS) == 7
    egfr = next(r for r in t["rows"] if "eGFR" in r[0]["text"])
    assert egfr[2]["text"] == "70 / 100" and egfr[3]["text"] == "70.0%" and egfr[4]["chip"] == "ok"
    bp = next(r for r in t["rows"] if "ความดัน" in r[0]["text"])
    assert bp[1]["text"] == "—" and bp[4] == ""                    # ไม่มีเป้า → ไม่ตัดสินผ่าน/ไม่ผ่าน


def test_one_failed_table_only_breaks_its_row(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get(errors={"s_kpi_ckd_statin"}))
    t = _kpi_table(hdc_views.build_ckd(P))
    statin = next(r for r in t["rows"] if "Statin" in r[0]["text"])
    assert statin[2]["text"] == hdc_views.NA
    assert sum(1 for r in t["rows"] if r[2]["text"] == hdc_views.NA) == 1


def test_new_ckd_kpi_and_unit_table(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get())
    d = hdc_views.build_ckd(P)
    assert any(k["label"] == "CKD รายใหม่ปีงบ (HDC)" and k["value"] == "45" for k in d["kpis"])
    inc = next(x for x in d["extra"] if x.get("title", "").startswith("ผู้ป่วย CKD รายใหม่รายหน่วยบริการ"))
    assert [r[1] for r in inc["rows"]] == ["33", "12"]
