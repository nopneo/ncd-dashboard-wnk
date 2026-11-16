"""ตัวชี้วัดการชะลอไตเสื่อม (หน้า CKD ฝั่ง HOSxP) — ใช้ข้อมูลของ รพ. เองทั้งหมด
1 DM/HT เป็น CKD รายใหม่ · 2 DM ได้ตรวจ Microalbumin · 3 CKD ได้รับ ACEI/ARB · 4 CKD 3–5 Hb >10 หรือ Hct >30
5 DM ที่มี CKD 3–4 HbA1c ควบคุมได้ · 6 Admit ซ้ำใน 28 วัน / เสียชีวิต"""
from datetime import date

import config
import periods
from queries import ckd

P = periods.make(2569)
D = date


def coh(**stages):
    return {hn: {"stage": st, "egfr": None} for hn, st in stages.items()}


def row(rows, name):
    return next(r for r in rows if r["key"] == name)


def base(**kw):
    args = dict(cohort={}, prior_ckd=set(), dm=set(), ht=set(), dm_visited=set(), uacr_tested=set(),
                visited=set(), acei=set(), hb={}, hct={}, a1c={}, dialysis=set())
    args.update(kw)
    return ckd.slowdown(**args)


# --- 1 รายใหม่ -----------------------------------------------------------------------

def test_new_ckd_among_dm_ht_excludes_those_already_ckd_before_period():
    rows = base(cohort=coh(A="G3a", B="G3b", X="G4"), prior_ckd={"B"}, dm={"A", "B", "C"}, ht={"C", "D"})
    r = row(rows, "new_ckd")
    assert (r["num"], r["den"]) == (1, 3)          # A ใหม่ · B เป็นอยู่แล้ว (ไม่นับทั้งตัวตั้ง/ตัวหาร) · X ไม่ใช่ DM/HT


# --- 2 Microalbumin ----------------------------------------------------------------

def test_microalbumin_screening_among_dm_who_visited():
    r = row(base(dm_visited={"A", "B", "C", "D"}, uacr_tested={"A", "B", "Z"}), "uacr")
    assert (r["num"], r["den"]) == (2, 4)


# --- 3 ACEI/ARB --------------------------------------------------------------------

def test_acei_arb_among_ckd_who_visited_excluding_stage5_and_dialysis():
    rows = base(cohort=coh(A="G3a", B="G4", C="G5", E="G3b", F=None), visited={"A", "B", "C", "E", "F"},
                acei={"A", "C", "F"}, dialysis={"E"})
    r = row(rows, "acei")
    assert (r["num"], r["den"]) == (2, 3)          # ตัวหาร A,B,F (C ระยะ 5 · E ล้างไต ไม่นับ) · ได้ยา A,F


# --- 4 ซีด -----------------------------------------------------------------------------

def test_anemia_target_uses_latest_hb_or_hct_among_tested_stage3_to_5():
    rows = base(cohort=coh(A="G3a", B="G4", C="G5", D="G3b", E="G1-2"),
                hb={"A": 10.5, "B": 9.0, "E": 8.0}, hct={"B": 31.0, "C": 28.0})
    r = row(rows, "anemia")
    assert (r["num"], r["den"]) == (2, 3)          # ตรวจแล้ว A,B,C (D ไม่ได้ตรวจ · E ระยะ 1–2) · ผ่าน A (Hb) B (Hct)
    t = row(rows, "anemia_tested")
    assert (t["num"], t["den"]) == (3, 4)


def test_anemia_threshold_is_strictly_greater_than(monkeypatch):
    monkeypatch.setattr(config, "CKD_HB_MIN", 10.0)
    monkeypatch.setattr(config, "CKD_HCT_MIN", 30.0)
    r = row(base(cohort=coh(A="G3a", B="G3a"), hb={"A": 10.0}, hct={"B": 30.0}), "anemia")
    assert (r["num"], r["den"]) == (0, 2)


# --- 5 DM + CKD 3–4 HbA1c ------------------------------------------------------------

def test_dm_ckd34_a1c_control_counts_untested_in_denominator(monkeypatch):
    monkeypatch.setattr(config, "CKD_DM_HBA1C_TARGET", 7.0)
    rows = base(cohort=coh(A="G3a", B="G3b", C="G4", D="G5", E="G3a"), dm={"A", "B", "C", "D"},
                a1c={"A": 6.8, "B": 7.0, "D": 6.0})
    r = row(rows, "dm_a1c")
    assert (r["num"], r["den"]) == (1, 3)          # A,B,C (D ระยะ 5 · E ไม่ใช่ DM) · ผ่าน A · C ไม่มีผล = ไม่ผ่าน


def test_targets_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "TARGET_CKD_ACEI_ARB", 70.0)
    assert row(base(), "acei")["target"] == 70.0


def test_empty_rows_have_no_percent():
    assert all(r["num"] == 0 and r["den"] == 0 for r in base())


# --- 6 Admit ซ้ำ -----------------------------------------------------------------------

def test_readmit_within_28_days_after_previous_discharge():
    rows = [{"hn": "A", "regdate": D(2026, 1, 1), "dchdate": D(2026, 1, 5)},
            {"hn": "A", "regdate": D(2026, 2, 2), "dchdate": D(2026, 2, 4)},     # 28 วันหลังจำหน่าย → นับ
            {"hn": "A", "regdate": D(2026, 4, 1), "dchdate": D(2026, 4, 3)},     # 56 วัน → ไม่นับ
            {"hn": "B", "regdate": D(2026, 1, 10), "dchdate": None},
            {"hn": "B", "regdate": D(2026, 1, 20), "dchdate": D(2026, 1, 22)}]   # ครั้งก่อนยังไม่จำหน่าย → ใช้วันรับ
    assert ckd.count_readmits(rows, days=28) == 2


def test_readmit_handles_unsorted_and_empty():
    assert ckd.count_readmits([]) == 0
    rows = [{"hn": "A", "regdate": D(2026, 1, 20), "dchdate": D(2026, 1, 22)},
            {"hn": "A", "regdate": D(2026, 1, 1), "dchdate": D(2026, 1, 5)}]
    assert ckd.count_readmits(rows) == 1


# --- ทั้งหน้า ----------------------------------------------------------------------------

def test_slowdown_table_rendered_on_ckd_page(fake_db):
    fake_db.add("from lab_head", [{"hn": "A", "result": "55", "d": D(2025, 12, 1)}, {"hn": "A", "result": "50", "d": D(2026, 4, 5)}])
    d = ckd.build(P)
    tables = [x for x in d["extra"] if x.get("title", "").startswith("ตัวชี้วัดการชะลอไตเสื่อม")]
    assert tables and "error" not in tables[0] and len(tables[0]["rows"]) == 6
    assert "โนนสูง" not in str(d)
