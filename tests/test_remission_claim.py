"""เกณฑ์การเบิก DM Remission (กรอบแนวทางงบบริการ — เอกสารแนบ 2)
- ยังไม่เริ่มยา: lifestyle ≥180 วันจากลงทะเบียน (1I20) และไม่มียาย้อนหลัง → HbA1c <6.5 ครั้งที่ 1
- รักษาด้วยยา: หยุดยา ≥90 วันก่อน HbA1c ครั้งที่ 1
- ครั้งที่ 2 ห่างจากครั้งที่ 1 ≥90 วัน (ผลระหว่างนั้นต้อง <6.5 และไม่มียา) → Successful case (เบิก 4,000)
- ครั้งที่ 3 ห่างจากครั้งที่ 2 90–180 วัน ยัง <6.5 ไม่มียา → Maintenance case (เบิก 2,000)"""
from datetime import date

import pytest

import config
from queries import remission_claim as rc

D = date
REG = D(2024, 1, 1)


def st(pts, drugs=(), reg=REG, today=D(2026, 1, 1)):
    return rc.claim_status(pts, list(drugs), reg, today)


def test_never_on_drug_pair_90_days_apart_is_success_then_waits_for_third():
    r = st([(D(2025, 7, 20), 6.2), (D(2025, 11, 1), 6.0)], reg=D(2025, 1, 1), today=D(2026, 1, 15))
    assert r["status"] == "wait3" and r["second"][0] == D(2025, 11, 1)
    assert (r["next_from"], r["next_to"]) == (D(2026, 1, 30), D(2026, 4, 30))


def test_never_on_drug_first_result_needs_180_days_lifestyle():
    r = st([(D(2025, 3, 1), 6.2), (D(2025, 6, 15), 6.0)], reg=D(2025, 1, 1), today=D(2025, 6, 20))
    assert r["status"] == "wait1" and r["first"] is None and r["next_from"] == D(2025, 6, 30)


def test_on_drug_first_result_needs_90_drug_free_days():
    pts = [(D(2025, 4, 1), 6.3), (D(2025, 6, 1), 6.2), (D(2025, 9, 5), 6.1)]
    r = st(pts, [D(2025, 2, 1)], reg=D(2025, 1, 1), today=D(2025, 9, 10))
    assert r["status"] == "wait3" and r["first"][0] == D(2025, 6, 1)        # 1 เม.ย. หยุดยาแค่ 59 วัน ไม่นับ


def test_drug_between_first_and_second_breaks_the_pair():
    r = st([(D(2025, 6, 1), 6.2), (D(2025, 9, 10), 6.0)], [D(2025, 7, 1)], today=D(2025, 9, 20))
    assert r["status"] == "on_drug" and r["second"] is None and r["next_from"] == D(2025, 9, 29)


def test_value_at_or_above_cutoff_restarts_pairing(monkeypatch):
    monkeypatch.setattr(config, "REMISSION_HBA1C", 6.5)
    pts = [(D(2025, 1, 10), 6.2), (D(2025, 3, 1), 6.5), (D(2025, 5, 1), 6.1), (D(2025, 6, 15), 6.0)]
    r = st(pts, today=D(2025, 7, 1))
    assert r["status"] == "wait2" and r["first"][0] == D(2025, 5, 1) and r["next_from"] == D(2025, 7, 30)


def test_low_value_in_between_keeps_the_first_of_the_pair():
    r = st([(D(2025, 1, 10), 6.2), (D(2025, 2, 10), 6.0), (D(2025, 4, 15), 6.1)], today=D(2025, 5, 1))
    assert r["first"][0] == D(2025, 1, 10) and r["second"][0] == D(2025, 4, 15)


def test_third_result_in_window_is_maintenance():
    pts = [(D(2025, 1, 10), 6.2), (D(2025, 4, 15), 6.1), (D(2025, 8, 1), 6.0)]
    r = st(pts, today=D(2025, 9, 1))
    assert r["status"] == "maint_done" and r["third"][0] == D(2025, 8, 1)
    assert [(c["kind"], c["date"], c["baht"]) for c in rc.claims(r)] == [
        ("success", D(2025, 4, 15), config.CLAIM_SUCCESS_BAHT), ("maint", D(2025, 8, 1), config.CLAIM_MAINT_BAHT)]


@pytest.mark.parametrize("pts,drugs,today", [
    ([(D(2025, 1, 10), 6.2), (D(2025, 4, 15), 6.1)], [], D(2025, 11, 1)),                         # เลย 180 วันแล้วไม่มีผล
    ([(D(2025, 1, 10), 6.2), (D(2025, 4, 15), 6.1)], [D(2025, 6, 1)], D(2025, 8, 1)),             # ได้ยาหลังสำเร็จ
    ([(D(2025, 1, 10), 6.2), (D(2025, 4, 15), 6.1), (D(2025, 6, 1), 7.0)], [], D(2025, 8, 1)),    # ผล ≥6.5 ก่อนครั้งที่ 3
])
def test_maintenance_lost_keeps_success(pts, drugs, today):
    r = st(pts, drugs, today=today)
    assert r["status"] == "success" and r["third"] is None
    assert [c["kind"] for c in rc.claims(r)] == ["success"]


def test_due_now_states():
    assert st([(D(2025, 1, 10), 6.2)], today=D(2025, 4, 20))["status"] == "due2"
    r = st([(D(2025, 1, 10), 6.2), (D(2025, 4, 15), 6.1)], today=D(2025, 8, 1))
    assert r["status"] == "due3" and r["next_to"] == D(2025, 10, 12)


def test_no_countable_first_result_but_eligible_is_need1():
    assert st([(D(2025, 3, 1), 7.0)], today=D(2025, 5, 1))["status"] == "need1"
    assert st([], today=D(2025, 5, 1))["status"] == "need1"


def test_pair_ceiling_is_optional(monkeypatch):
    pts = [(D(2025, 1, 10), 6.2), (D(2025, 7, 30), 6.1)]          # ห่าง 201 วัน
    assert st(pts, today=D(2025, 8, 1))["status"] == "wait3"
    monkeypatch.setattr(config, "CLAIM_PAIR_MAX_DAYS", 180)
    r = st(pts, today=D(2025, 8, 1))
    assert r["status"] == "wait2" and r["first"][0] == D(2025, 7, 30)


def test_first_registration_date_query(fake_db):
    from queries import common
    fake_db.add("min(s.entry_datetime)", [{"hn": "A", "d": D(2025, 1, 21)}, {"hn": None, "d": D(2025, 2, 1)}])
    assert common.pp_special_first_dates(["1I20"]) == {"A": D(2025, 1, 21)}
    assert "pp_special_code in" in fake_db.calls[0][0]


# --- หน้า DM + รายชื่อ (เฉพาะ LAN) ---------------------------------------------------------

LAN = {"REMOTE_ADDR": "192.168.11.5"}
VIA_INTERNET = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "1.1.1.1"}}


@pytest.fixture
def fake_claim(monkeypatch, fake_db):
    from queries import common
    today = D(2026, 5, 1)
    monkeypatch.setattr(common, "today", lambda: today)
    monkeypatch.setattr(common, "pp_special_first_dates", lambda codes: {"R1": D(2024, 1, 1), "R2": D(2024, 1, 1), "R3": D(2026, 3, 1)})
    monkeypatch.setattr(common, "lab_series_by_hn", lambda code, clinic, s, e, allow_zero=False: {
        "R1": [(D(2025, 10, 10), 6.2), (D(2026, 1, 20), 6.1)],          # สำเร็จ 20 ม.ค. 69 → รอครั้งที่ 3 (20 เม.ย.–19 ก.ค.) = due3
        "R2": [(D(2026, 3, 1), 6.0)]})                                    # ครั้งที่ 1 → due2 ตั้งแต่ 30 พ.ค. = wait2
    monkeypatch.setattr(common, "drug_dates_by_hn", lambda icodes, hns, s, e: {})
    rc._MEMO.clear()
    fake_db.add("from patient p", [{"hn": "R1", "pname": "นาง", "fname": "สงบ", "lname": "ดี", "birthday": D(1970, 1, 1)}])
    yield fake_db
    rc._MEMO.clear()


def test_section_counts_and_claim_money(fake_claim):
    import periods
    t = rc.section(periods.make(2569))
    flat = {r[0]["text"]: r[1]["text"] for r in t["rows"]}
    assert flat[rc.LABEL["due3"][0]] == "1 ราย" and flat[rc.LABEL["wait2"][0]] == "1 ราย" and flat[rc.LABEL["wait1"][0]] == "1 ราย"
    assert t["rows"][0][1]["text"] == "4,000 บาท"                         # R1 ยืนยันผล 20 ม.ค. 69 อยู่ในปีงบ 2569


def test_claim_links_and_list_are_lan_only(fake_claim):
    from app import app
    c = app.test_client()
    lan = c.get("/dm?fy=2569", environ_base=LAN).get_data(as_text=True)
    assert "/list/dm/claim?fy=2569&amp;g=due3" in lan and "/list/dm/claim?fy=2569&amp;g=all" in lan
    assert "/list/" not in c.get("/dm?fy=2569", **VIA_INTERNET).get_data(as_text=True)
    r = c.get("/list/dm/claim?fy=2569&g=due3", environ_base=LAN)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "R1" in html and "สงบ" in html and "R2" not in html
    assert c.get("/list/dm/claim?g=all", **VIA_INTERNET).status_code == 403
    assert c.get("/list/dm/claim?g=zzz", environ_base=LAN).status_code == 404


def test_results_before_registration_do_not_count():
    r = st([(D(2024, 6, 1), 6.2), (D(2024, 9, 15), 6.0)], reg=D(2025, 1, 1), today=D(2025, 2, 1))
    assert r["second"] is None and r["status"] == "wait1"
