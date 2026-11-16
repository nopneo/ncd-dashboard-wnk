from datetime import date, timedelta

import pytest

from classify import (bp_group, ckd_stage, egfr_slope_per_year, hba1c_group, inr_group,
                      parse_result, ttr_rosendaal, valid_bp)


@pytest.mark.parametrize("text,expected", [
    ("7.2", 7.2), (" 7.2 ", 7.2), ("1,234.5", 1234.5), ("7,2", None),
    ("<5.0", 5.0), (">90", 90.0), ("", None), (None, None), ("pending", None), ("-", None),
    (7.5, 7.5),
    # ผลที่มีคำอธิบายต่อท้าย — eGFR ก่อน ธ.ค. 2568 ของ รพ.วังน้ำเขียวเก็บเป็น "90.58 [Stage 1]" (พบจากข้อมูลจริง)
    ("90.58 [Stage 1]", 90.58), ("5.2 mg/dl", 5.2), ("7.5 %", 7.5), ("12 (H)", 12.0), ("1,234.5 [x]", 1234.5), (">90 [Stage 1]", 90.0),
    ("7.2.1", None), ("pending 5", None), ("7,2 [x]", None), ("[Stage 1]", None),
])
def test_parse_result(text, expected):
    assert parse_result(text) == expected


@pytest.mark.parametrize("sbp,dbp,ok", [
    (120, 80, True), (0, 0, False), (999, 80, False), (80, 120, False), (None, 80, False),
])
def test_valid_bp(sbp, dbp, ok):
    assert valid_bp(sbp, dbp) is ok


@pytest.mark.parametrize("sbp,dbp,group", [
    (139, 89, "controlled"), (140, 80, "partial"), (159, 99, "partial"),
    (160, 70, "uncontrolled"), (120, 100, "uncontrolled"), (0, 0, None), (None, None, None),
])
def test_bp_group(sbp, dbp, group):
    assert bp_group(sbp, dbp) == group


@pytest.mark.parametrize("v,group", [
    (6.9, "lt7"), (7.0, "7to79"), (7.9, "7to79"), (8.0, "ge8"), (None, None),
])
def test_hba1c_group(v, group):
    assert hba1c_group(v) == group


@pytest.mark.parametrize("v,group", [(2.0, "in"), (3.0, "in"), (1.99, "low"), (3.01, "high"), (None, None)])
def test_inr_group(v, group):
    assert inr_group(v) == group


def test_inr_group_custom_range():
    assert inr_group(1.6, low=1.5, high=2.5) == "in"


@pytest.mark.parametrize("egfr,stage", [
    (60, "G1-2"), (59.9, "G3a"), (45, "G3a"), (44.9, "G3b"), (30, "G3b"),
    (29.9, "G4"), (15, "G4"), (14.9, "G5"), (None, None),
])
def test_ckd_stage(egfr, stage):
    assert ckd_stage(egfr) == stage


def test_egfr_slope_per_year():
    d = date(2025, 1, 1)
    pts = [(d, 60.0), (d + timedelta(days=182), 57.0), (d + timedelta(days=365), 54.0)]
    assert egfr_slope_per_year(pts) == pytest.approx(-6.0, abs=0.1)
    assert egfr_slope_per_year(pts[:1]) is None


def test_ttr_all_in_range():
    d = date(2026, 1, 1)
    assert ttr_rosendaal([(d, 2.0), (d + timedelta(days=10), 3.0)], 2.0, 3.0) == 100.0


def test_ttr_half_in_range():
    d = date(2026, 1, 1)
    assert ttr_rosendaal([(d, 1.0), (d + timedelta(days=10), 3.0)], 2.0, 3.0) == 50.0


def test_ttr_needs_two_points():
    assert ttr_rosendaal([(date(2026, 1, 1), 2.5)], 2.0, 3.0) is None
