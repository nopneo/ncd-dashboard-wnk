import pages
import periods
from queries import copd

P = periods.make(2569)


def clinics_used(fake_db):
    return {a["clinic"] for _s, a, _b in fake_db.calls if a and "clinic" in a}


def test_group_to_clinics():
    import config
    assert copd.grp_clinics("copd") == [config.CLINIC_COPD]
    assert copd.grp_clinics("asthma") == [config.CLINIC_ASTHMA]
    assert copd.grp_clinics("all") == [config.CLINIC_COPD, config.CLINIC_ASTHMA]
    assert copd.grp_clinics("zzz") == copd.grp_clinics("all")


def _seed(fake_db):
    fake_db.add("group by m.hn", [{"hn": "1"}, {"hn": "2"}, {"hn": "3"}])
    fake_db.add("select distinct o.hn", [{"hn": "1"}, {"hn": "2"}])
    fake_db.add("select distinct r.hn", [{"hn": "1"}])


def test_build_all_counts_union_of_registries(fake_db):
    _seed(fake_db)
    d = copd.build(P)
    assert d["kpis"][0]["value"] == "3"                      # ทั้งสองคลินิกคืน hn ชุดเดียวกัน → ไม่นับซ้ำ
    assert clinics_used(fake_db) == {"024", "023"}
    assert "error" not in d["monthly"] and all("error" not in x for x in d["extra"])


def test_build_copd_only_uses_clinic_024(fake_db):
    _seed(fake_db)
    d = copd.build(P, "hosxp", {"grp": "copd"})
    assert clinics_used(fake_db) == {"024"} and "COPD" in d["subtitle"]


def test_build_asthma_only_uses_clinic_023(fake_db):
    _seed(fake_db)
    copd.build(P, "hosxp", {"grp": "asthma"})
    assert clinics_used(fake_db) == {"023"}


def test_table_marks_missing_sources_when_config_empty(fake_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "PROC_SPIROMETRY", [])
    monkeypatch.setattr(config, "DRUG_INHALER_CONTROLLER", [])
    _seed(fake_db)
    d = copd.build(P)
    flat = {(r[0]["text"] if isinstance(r[0], dict) else r[0]): r[2] for r in d["table"]["rows"]}   # ชื่อแถวมีลิงก์รายชื่อได้
    assert flat["ร้อยละที่เคยได้รับการตรวจสมรรถภาพปอด (ทุกช่วงเวลา)"] == "ไม่มีข้อมูล"
    assert flat["ร้อยละที่ได้รับยาพ่นควบคุมอาการ"] == "ไม่มีข้อมูล"


def test_registry_gap_tile(fake_db):
    _seed(fake_db)
    fake_db.add("ovstdiag", [{"hn": "1"}, {"hn": "99"}])       # hn 99 มีรหัสโรคแต่ไม่อยู่ในทะเบียน
    d = copd.build(P)
    tiles = next(x for x in d["extra"] if x.get("type") == "tiles" and "ทะเบียน" in x["title"])
    assert any(i["value"] == "1" for i in tiles["items"])


def test_empty_registry(fake_db):
    d = copd.build(periods.make(2570))
    assert d["kpis"][0]["value"] in ("0", "—") and d["donut"]["center"] == "—"


def test_hdc_delegates(monkeypatch):
    from queries import hdc_views
    monkeypatch.setattr(hdc_views, "build_copd", lambda p: {"title": "HDC COPD"})
    assert copd.build(P, "hdc")["title"] == "HDC COPD"


def test_registered():
    pages.load()
    assert pages.REGISTRY["copd"] is copd.build


def test_spirometry_looks_back_over_all_time(fake_db):
    """สมรรถภาพปอดมักตรวจครั้งเดียวตอนวินิจฉัย — ต้องนับย้อนหลังทุกช่วงเวลา ไม่ใช่แค่ในช่วงที่เลือก"""
    _seed(fake_db)
    copd.build(P)
    spiro_calls = [a for _s, a, b in fake_db.calls if a and a.get("c0") == "3160033"]
    assert spiro_calls and spiro_calls[0]["start"].year <= 2000
