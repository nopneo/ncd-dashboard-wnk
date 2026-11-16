import pages
import periods
from queries import overview

P = periods.make(2569)


def page(title, v0, v1, lab1="ตัวชี้วัดหลัก", sub1="x", notes=None):
    return {"title": title, "kpis": [{"label": "ผู้ป่วย", "value": v0, "sub": "s0"},
                                     {"label": lab1, "value": v1, "sub": sub1}], "notes": notes or []}


def fake_pages(monkeypatch, errors=()):
    def get(key, p, src="hosxp", opts=None):
        if key in errors:
            return {"title": key, "page_error": "ดึงข้อมูลไม่ได้"}
        return page(pages.title_of(key), "100", "50.0%", notes=[{"tone": "warn", "text": f"{key} ต่ำกว่าเป้า"}])

    monkeypatch.setattr(pages, "get", get)
    monkeypatch.setattr(overview, "_patient_sets", lambda p: {"ht": {"1", "2", "3"}, "dm": {"3", "4"}, "ckd": {"4"}})
    monkeypatch.setattr(overview, "_trend", lambda p: {"labels": ["ปีงบ 2568", "ปีงบ 2569"], "series": [
        {"name": "HT", "values": [10, 12], "color": "#1"}, {"name": "DM", "values": [5, 6], "color": "#2"}]})


def test_distinct_patients_does_not_double_count():
    d = overview.distinct_patients({"ht": {"1", "2", "3"}, "dm": {"3", "4"}, "ckd": {"4"}})
    assert d["total_unique"] == 4 and d["overlap_ht_dm"] == 1 and d["multi_disease"] == 2
    assert d["by_disease"] == {"ht": 3, "dm": 2, "ckd": 1}


def test_distinct_patients_empty():
    assert overview.distinct_patients({})["total_unique"] == 0


def test_build_cards_one_per_disease(monkeypatch):
    fake_pages(monkeypatch)
    d = overview.build(P)
    assert len(d["kpis"]) == 6
    titles = [k["label"] for k in d["kpis"]]
    assert titles == [pages.title_of(k) for k in ("ht", "dm", "ckd", "warfarin", "copd", "cvd")]
    assert all(k["value"] == "100" for k in d["kpis"])


def test_error_page_becomes_dash_card_not_crash(monkeypatch):
    fake_pages(monkeypatch, errors=("dm",))
    d = overview.build(P)
    dm_card = d["kpis"][1]
    assert dm_card["value"] == "—" and "ดึงข้อมูลไม่ได้" in dm_card["sub"]
    assert d["table"]["rows"][1][2] == "—"


def test_summary_table_and_unique_tile(monkeypatch):
    fake_pages(monkeypatch)
    d = overview.build(P)
    assert len(d["table"]["rows"]) == 6
    tiles = next(x for x in d["extra"] if x["type"] == "tiles")
    assert any(i["value"] == "4" for i in tiles["items"])             # ผู้ป่วย NCD ไม่ซ้ำ ไม่ใช่ 6 (3+2+1)


def test_notes_collect_first_warning_of_each_page_with_prefix(monkeypatch):
    fake_pages(monkeypatch)
    d = overview.build(P)
    assert len(d["notes"]) == 6 and all("ต่ำกว่าเป้า" in n["text"] for n in d["notes"])
    assert d["notes"][0]["text"].startswith("ความดันโลหิตสูง")


def test_trend_series_present(monkeypatch):
    fake_pages(monkeypatch)
    d = overview.build(P)
    assert d["monthly"]["labels"][0] == "ปีงบ 2568"


def test_hdc_delegates(monkeypatch):
    from queries import hdc_views
    monkeypatch.setattr(hdc_views, "build_overview", lambda p: {"title": "HDC ภาพรวม"})
    assert overview.build(P, "hdc")["title"] == "HDC ภาพรวม"


def test_real_patient_sets_run_on_empty_db(fake_db):
    sets = overview._patient_sets(P)
    assert set(sets) == {"ht", "dm", "ckd", "warfarin", "copd", "cvd"} and all(isinstance(v, set) for v in sets.values())


def test_registered():
    pages.load()
    assert pages.REGISTRY["overview"] is overview.build
