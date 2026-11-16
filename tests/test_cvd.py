import pages
import periods
from queries import cvd

P = periods.make(2569)


def test_split_new_vs_prior():
    assert cvd.split_new_vs_prior({"1", "2", "3"}, {"2"}) == {"new": 2, "prior_known": 1, "total": 3}
    assert cvd.split_new_vs_prior(set(), {"2"}) == {"new": 0, "prior_known": 0, "total": 0}


def test_registry_overlap_does_not_double_count_ht_and_dm():
    o = cvd.registry_overlap({"1", "2", "3", "4"}, ht={"1", "2"}, dm={"2", "3"})
    assert (o["total"], o["in_ht"], o["in_dm"], o["in_any"], o["in_neither"]) == (4, 2, 2, 3, 1)
    assert o["in_any"] + o["in_neither"] == o["total"]
    assert o["in_neither_pct"] == 25.0


def test_registry_overlap_empty():
    o = cvd.registry_overlap(set(), set(), set())
    assert o["total"] == 0 and o["in_neither_pct"] is None


def test_secondary_prevention_denominators():
    r = cvd.secondary_prevention(cohort={"1", "2", "3", "4"}, statin={"1", "2"}, antithrombotic={"1"},
                                 bp={"1": (120.0, 80.0), "2": (150.0, 90.0)}, hba1c={"1": 6.5, "2": 8.0},
                                 dm={"1", "2", "9"}, visited={"1", "2", "3"})
    assert r["statin_pct"] == 50.0 and r["antithrombotic_pct"] == 25.0
    assert r["bp_controlled_pct"] == 25.0                     # ตัวหาร = ทั้งกลุ่ม (คนไม่มีค่านับในตัวหาร)
    assert r["hba1c_lt7_pct"] == 50.0                         # ตัวหาร = เฉพาะกลุ่มที่เป็น DM (hn 9 ไม่อยู่ในกลุ่ม)
    assert r["visited_pct"] == 75.0 and r["dm_in_cohort"] == 2


def test_secondary_prevention_empty_cohort():
    r = cvd.secondary_prevention(set(), set(), set(), {}, {}, set(), set())
    assert r["statin_pct"] is None and r["bp_controlled_pct"] is None and r["hba1c_lt7_pct"] is None


def _seed(fake_db):
    fake_db.add("ovstdiag", [{"hn": "1"}, {"hn": "2"}, {"hn": "3"}])
    fake_db.add("group by m.hn", [{"hn": "1"}, {"hn": "9"}])
    fake_db.add("count(distinct d.an)", [{"n": 5}])


def test_build_sections(fake_db):
    _seed(fake_db)
    d = cvd.build(P)
    assert len(d["kpis"]) == 4 and "error" not in d["donut"]
    assert all("error" not in x for x in d["extra"]), [x for x in d["extra"] if "error" in x]
    titles = " ".join(x["title"] for x in d["extra"])
    assert "ป้องกันการเป็นซ้ำ" in titles and "ทะเบียน HT/DM" in titles


def test_icd_prefixes_come_from_config_not_literals(fake_db):
    import config
    _seed(fake_db)
    cvd.build(P)
    used = {v for _s, a, _b in fake_db.calls if a for k, v in a.items() if k.startswith("i")}
    assert "I63%" in used and "I21%" in used and set(config.ICD_STROKE) | set(config.ICD_AMI)


def test_build_no_patients(fake_db):
    d = cvd.build(periods.make(2570))
    assert d["donut"]["center"] == "—"
    assert "—" in str(d["extra"])


def test_hdc_delegates(monkeypatch):
    from queries import hdc_views
    monkeypatch.setattr(hdc_views, "build_cvd", lambda p: {"title": "HDC CVD"})
    assert cvd.build(P, "hdc")["title"] == "HDC CVD"


def test_registered():
    pages.load()
    assert pages.REGISTRY["cvd"] is cvd.build
