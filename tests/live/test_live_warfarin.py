import periods
from queries import warfarin

P = periods.make(2569)


def test_cohort_and_inr_plausible():
    core = warfarin._core(P)
    s = core["summary"]
    print("WARFARIN", {k: s[k] for k in ("patients", "inr_total", "in_pct", "ttr_mean", "ttr_patients", "critical_gt45", "median_gap_days")}, "bleeding", core["bleeding"])
    assert 100 <= s["patients"] <= 300
    assert s["inr_in"] + s["inr_low"] + s["inr_high"] == s["inr_total"] > 500
    assert s["ttr_mean"] is not None and 0 <= s["ttr_mean"] <= 100


def test_build_has_no_section_errors():
    d = warfarin.build(P)
    assert "error" not in d["monthly"] and "error" not in d["donut"] and "error" not in d["recent"]
