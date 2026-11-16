import time

import periods
from queries import ckd

P = periods.make(2569)


def test_cohort_is_plausible_and_consistent():
    t = time.time()
    core = ckd._core(P)
    s = core["summary"]
    assert 100 <= s["total"] <= 3000, s
    assert s["g3a"] + s["g3b"] + s["g4"] + s["g5"] + s["g12"] + s["unknown"] == s["total"]
    print("CKD", s, "dialysis", core["dialysis"], "admits", core["admits"], round(time.time() - t, 1), "s")


def test_build_has_no_section_errors():
    d = ckd.build(P)
    assert "error" not in d["monthly"] and "error" not in d["donut"] and all("error" not in x for x in d["extra"])
