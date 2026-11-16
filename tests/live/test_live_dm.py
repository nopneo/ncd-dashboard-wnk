import periods
from queries import common, dm

P = periods.make(2569)


def test_hba1c_groups_sum_to_registry():
    reg = common.registry_count("001", P)
    assert 2500 <= reg <= 3500
    latest = common.latest_lab_by_hn(271, "001", P)
    s = dm.summarize_hba1c(latest, reg)
    assert s["lt7"] + s["7to79"] + s["ge8"] + s["no_value"] == reg
    assert s["tested"] > 500


def test_build_has_no_section_errors():
    d = dm.build(P)
    assert "error" not in d["monthly"] and "error" not in d["donut"] and "error" not in d["recent"]
    assert all("error" not in x for x in d["extra"]), [x for x in d["extra"] if "error" in x]
