import periods
from queries import copd

P = periods.make(2569)


def test_registry_counts_and_sections():
    core = copd._core(P, "all")
    print("COPD", {c: len(h) for c, h in core["regs"].items()}, "unique", len(core["registry"]), "visited", len(core["visited"]),
          "gap", core["gap"], "admits", core["admits"], "spiro", None if core["spiro"] is None else len(core["spiro"] & core["registry"]),
          "inhaler", None if core["inhaler"] is None else len(core["inhaler"] & core["registry"]), "lost", core["lost"])
    assert 100 <= len(core["registry"]) <= 220


def test_build_each_group_has_no_errors():
    for g in ("all", "copd", "asthma"):
        d = copd.build(P, "hosxp", {"grp": g})
        assert "error" not in d["monthly"] and "error" not in d["donut"] and all("error" not in x for x in d["extra"])
