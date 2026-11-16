"""ทดสอบกับฐาน HOSxP จริง (อ่านอย่างเดียว) — รัน: NCD_LIVE=1 NCD_DB_MODE=keyring NCD_DB_HOST=<IP ฐาน HOSxP> python -m pytest tests/live"""
import periods
from queries import common, ht

P = periods.make(2569)


def test_registry_and_groups_consistent():
    reg = common.registry_count("002", P)
    assert 3000 <= reg <= 4600
    series = ht.bp_series_by_hn("002", P)
    s = ht.summarize(ht.latest_rows(series), reg)
    assert s["controlled"] + s["partial"] + s["uncontrolled"] + s["no_value"] == reg
    assert s["tested"] > 0


def test_build_has_no_section_errors():
    d = ht.build(P)
    assert "error" not in d["kpis"] if isinstance(d["kpis"], dict) else True
    assert "error" not in d["monthly"] and "error" not in d["donut"] and "error" not in d["recent"]
    assert all("error" not in x for x in d["extra"])
