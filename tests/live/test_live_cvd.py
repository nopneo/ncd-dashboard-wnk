import periods
from queries import cvd

P = periods.make(2569)


def test_cvd_numbers_plausible_and_consistent():
    core = cvd._core(P)
    o, s = core["overlap"], core["sec"]
    print("CVD stroke", len(core["stroke"]), "ami", len(core["ami"]), "split", core["split"], "cohort", len(core["cohort"]),
          "admits", core["admits"], "deaths", core["deaths"], "sec", s, "overlap", o, core["types"])
    assert len(core["stroke"]) > 100 and len(core["ami"]) > 5
    assert o["in_any"] + o["in_neither"] == o["total"] == len(core["cohort"])
    assert core["split"]["new"] + core["split"]["prior_known"] == len(core["current"])


def test_build_has_no_section_errors():
    d = cvd.build(P)
    assert "error" not in d["donut"] and all("error" not in x for x in d["extra"])
