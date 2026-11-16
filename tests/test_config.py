import importlib

import config


def test_env_overrides_default(monkeypatch):
    monkeypatch.setenv("NCD_CLINIC_HT", "009")
    importlib.reload(config)
    assert config.CLINIC_HT == "009"
    monkeypatch.delenv("NCD_CLINIC_HT")
    importlib.reload(config)
    assert config.CLINIC_HT == "002"


def test_get_list_splits_and_strips():
    import os
    os.environ["NCD_TMP_LIST"] = "I60, I61,,"
    try:
        assert config.get_list("TMP_LIST", "") == ["I60", "I61"]
    finally:
        del os.environ["NCD_TMP_LIST"]


def test_default_inr_range_and_clinics():
    assert (config.INR_LOW, config.INR_HIGH) == (2.0, 3.0)
    assert (config.CLINIC_DM, config.CLINIC_COPD, config.CLINIC_ASTHMA) == ("001", "024", "023")
    assert config.DRUG_WARFARIN == ["1000102", "1000104"]
    assert (config.LAB_HBA1C, config.LAB_INR, config.LAB_EGFR) == (271, 2020, 2135)
