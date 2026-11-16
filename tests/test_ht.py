from datetime import date

import pages
import periods
from queries import ht

P = periods.make(2569)


def mk(hn, sbp, dbp):
    return {"hn": hn, "sbp": sbp, "dbp": dbp, "date": date(2026, 1, 1)}


def test_summarize_counts_untested_in_denominator():
    latest = ([mk(str(i), 120, 80) for i in range(6)] + [mk("6", 145, 85), mk("7", 150, 95),
              mk("8", 170, 100), mk("9", 0, 0)])
    s = ht.summarize(latest, registry=12)
    assert (s["controlled"], s["partial"], s["uncontrolled"]) == (6, 2, 1)
    assert s["no_value"] == 3                       # ค่าผิด 1 + ไม่มีแถวเลย 2
    assert s["controlled_pct"] == 50.0 and s["tested_pct"] == 75.0


def test_summarize_zero_registry():
    s = ht.summarize([], registry=0)
    assert s["controlled_pct"] is None and s["tested_pct"] is None and s["no_value"] == 0


def test_uncontrolled_streak():
    s = [(date(2026, 1, 1), 120, 80), (date(2026, 2, 1), 165, 90), (date(2026, 3, 1), 150, 85)]
    assert ht.uncontrolled_streak(s, n=2) is True          # 2 ครั้งล่าสุดไม่ผ่าน <140/90
    assert ht.uncontrolled_streak(s[:2], n=2) is False
    assert ht.uncontrolled_streak(s[:1], n=2) is False


def test_bp_series_filters_invalid_and_orders(fake_db):
    fake_db.add("from opdscreen", [
        {"hn": "1", "sbp": 150.0, "dbp": 90.0, "d": date(2026, 2, 1)},
        {"hn": "1", "sbp": 0.0, "dbp": 0.0, "d": date(2026, 3, 1)},
        {"hn": "1", "sbp": 130.0, "dbp": 80.0, "d": date(2026, 1, 1)},
    ])
    s = ht.bp_series_by_hn("002", P)
    assert s == {"1": [(date(2026, 1, 1), 130.0, 80.0), (date(2026, 2, 1), 150.0, 90.0)]}


def _seed(fake_db):
    fake_db.add("count(distinct m.hn)", [{"n": 12}])
    fake_db.add("from opdscreen", [{"hn": str(i), "sbp": 120.0, "dbp": 80.0, "d": date(2026, 1, 1)} for i in range(6)])


def test_build_returns_all_sections(fake_db):
    _seed(fake_db)
    d = ht.build(P)
    assert d["title"] and len(d["kpis"]) == 4
    assert sum(v for _, v, _ in d["donut"]["parts"]) == 12        # โดนัทรวม = ทะเบียน
    assert d["table"]["columns"][0] == "ตัวชี้วัด"
    assert len(d["monthly"]["labels"]) == 12
    assert "error" not in d["recent"]
    assert all("error" not in x for x in d["extra"])           # ทุกส่วนเสริมต้องไม่ล้มเงียบ


def test_build_empty_period_has_no_exception_and_dashes(fake_db):
    d = ht.build(periods.make(2570))
    assert d["kpis"][0]["value"] in ("0", "—")
    assert d["donut"]["center"] == "—"


def test_one_failing_query_isolated(fake_db):
    _seed(fake_db)
    fake_db.responses.insert(0, ("group by date_format", RuntimeError("boom")))
    d = ht.build(P)
    assert "error" in d["monthly"]                  # ส่วนที่ล้ม
    assert len(d["kpis"]) == 4 and "error" not in d["donut"]


def test_sql_all_bind_cleanly(fake_db):
    _seed(fake_db)
    ht.build(P)
    assert fake_db.calls                             # FakeDB ตรวจ % หลุดผ่าน db._bind ทุกคำสั่ง


def test_registered_in_pages():
    pages.load()
    assert pages.REGISTRY["ht"] is ht.build
