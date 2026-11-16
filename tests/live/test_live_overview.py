import pages
import periods
from queries import overview

P = periods.make(2569)
pages.load()


def test_overview_all_cards_have_data_and_unique_count_is_not_sum():
    d = overview.build(P)
    print([(k["label"], k["value"], k["sub"]) for k in d["kpis"]])
    assert all(k["value"] != "—" for k in d["kpis"]), d["kpis"]
    tiles = d["extra"][0]
    assert "error" not in tiles
    sets = overview._patient_sets(P)
    dist = overview.distinct_patients(sets)
    print(dist)
    assert dist["total_unique"] < sum(dist["by_disease"].values())
    assert dist["overlap_ht_dm"] > 100
