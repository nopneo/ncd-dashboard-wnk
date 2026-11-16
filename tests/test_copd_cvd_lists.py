"""รายชื่อผู้ป่วยหน้า COPD/หืด และ CVD (เฉพาะ LAN) — กลุ่มต้องตรงกับตัวเลขบนหน้า"""
from datetime import date

import pytest

import config
import periods
from app import app
from queries import clinic_lists, common

P = periods.make(2569)
LAN = {"REMOTE_ADDR": "192.168.11.5"}
VIA_INTERNET = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "1.1.1.1"}}


@pytest.fixture
def fake_copd(monkeypatch, fake_db):
    regs = {config.CLINIC_COPD: ["C1", "C2", "B"], config.CLINIC_ASTHMA: ["A1", "B"]}
    visited = {config.CLINIC_COPD: {"C1", "B"}, config.CLINIC_ASTHMA: {"B"}}
    lost = {config.CLINIC_COPD: {"C2"}, config.CLINIC_ASTHMA: {"A1"}}
    monkeypatch.setattr(common, "registry_hns", lambda c, p: list(regs.get(c, [])))
    monkeypatch.setattr(common, "visited_hns", lambda c, p: set(visited.get(c, set())))
    monkeypatch.setattr(common, "followup_hns", lambda c, p, on: {"lost_3m": set(lost.get(c, set())), "overdue": set()})
    monkeypatch.setattr(common, "icd_hns", lambda ids, p, clinic=None: (
        {"C1", "X1"} if list(ids) == list(config.ICD_COPD) else {"A1", "X2"} if list(ids) == list(config.ICD_ASTHMA) else set()))
    monkeypatch.setattr(common, "drug_hns", lambda codes, clinic, p: (
        {"C1"} if list(codes) == list(config.PROC_SPIROMETRY) else {"C1", "A1"} if list(codes) == list(config.DRUG_INHALER_CONTROLLER) else set()))
    monkeypatch.setattr(common, "icd_admissions", lambda ids, p: 0)
    clinic_lists._MEMO.clear()
    yield fake_db
    clinic_lists._MEMO.clear()


def test_copd_groups_all(fake_copd):
    g, _v = clinic_lists.copd_groups(P, "all")
    assert g["registry"] == {"C1", "C2", "B", "A1"} and g["not_visited"] == {"C2", "A1"} and g["lost_3m"] == {"C2", "A1"}
    assert g["gap"] == {"X1", "X2"} and g["no_spiro"] == {"C2", "B", "A1"} and g["no_inhaler"] == {"C2", "B"}
    assert g["reg_copd"] == {"C1", "C2", "B"} and g["reg_asthma"] == {"A1", "B"}


def test_copd_groups_follow_selected_disease(fake_copd):
    g, v = clinic_lists.copd_groups(P, "copd")
    assert g["registry"] == {"C1", "C2", "B"} and g["gap"] == {"X1"} and g["lost_3m"] == {"C2"}
    assert v("B") == "COPD" and v("X1") == "ไม่อยู่ในทะเบียน"
    _g, v_all = clinic_lists.copd_groups(P, "all")
    assert v_all("B") == "COPD + หืด"


def test_copd_page_links_keep_disease_filter_and_are_lan_only(fake_copd):
    c = app.test_client()
    lan = c.get("/copd?fy=2569&grp=copd", environ_base=LAN).get_data(as_text=True)
    assert "/list/copd/group?fy=2569&amp;grp=copd&amp;g=gap" in lan and "g=no_inhaler" in lan and "g=lost_3m" in lan
    assert "/list/" not in c.get("/copd?fy=2569&grp=copd", **VIA_INTERNET).get_data(as_text=True)
    r = c.get("/list/copd/group?fy=2569&grp=copd&g=no_inhaler", environ_base=LAN)
    assert r.status_code == 200 and "C2" in r.get_data(as_text=True) and "A1" not in r.get_data(as_text=True)
    assert c.get("/list/copd/group?fy=2569&g=gap", **VIA_INTERNET).status_code == 403


@pytest.fixture
def fake_cvd(monkeypatch, fake_db):
    stroke, ami = list(config.ICD_STROKE), list(config.ICD_AMI)

    def icd(ids, p, clinic=None):
        ids = list(ids)
        if ids == stroke:
            return {"S1", "S2"}
        if ids == ami:
            return {"M1"}
        if ids == stroke + ami:
            return {"S2"} if p.end < P.start else {"S1", "S2", "M1", "Z9"}      # ก่อนช่วง (prior) / 3 ปี (cohort)
        return set()

    monkeypatch.setattr(common, "icd_hns", icd)
    monkeypatch.setattr(common, "drug_hns", lambda codes, clinic, p: (
        {"S1"} if list(codes) == list(config.DRUG_STATIN) else {"S1", "M1"}))
    monkeypatch.setattr(common, "bp_latest_for_hns", lambda hns, p: {"S1": (130, 80), "S2": (150, 95)})
    monkeypatch.setattr(common, "latest_lab_by_hn", lambda code, clinic, p, allow_zero=False: [{"hn": "M1", "value": 8.0, "date": date(2026, 1, 1)}])
    monkeypatch.setattr(common, "registry_hns", lambda c, p: ["M1", "S2"] if c == config.CLINIC_DM else ["S1"])
    monkeypatch.setattr(common, "visited_among", lambda hns, p: {"S1", "M1"})
    monkeypatch.setattr(common, "icd_admissions", lambda ids, p: 0)
    monkeypatch.setattr(common, "icd_deaths", lambda ids, st, p: 0)
    clinic_lists._MEMO.clear()
    yield fake_db
    clinic_lists._MEMO.clear()


def test_cvd_groups(fake_cvd):
    g, _v = clinic_lists.cvd_groups(P)
    assert g["stroke"] == {"S1", "S2"} and g["ami"] == {"M1"} and g["new"] == {"S1", "M1"} and g["prior_known"] == {"S2"}
    assert g["no_statin"] == {"S2", "M1", "Z9"} and g["no_antithrombotic"] == {"S2", "Z9"}
    assert g["bp_not_controlled"] == {"S2", "M1", "Z9"} and g["a1c_not"] == {"M1", "S2"}
    assert g["not_visited"] == {"S2", "Z9"} and g["in_neither"] == {"Z9"}


def test_cvd_page_links_lan_only(fake_cvd):
    c = app.test_client()
    lan = c.get("/cvd?fy=2569", environ_base=LAN).get_data(as_text=True)
    for g in ("new", "no_statin", "in_neither", "stroke", "ami"):
        assert f"g={g}" in lan
    assert "/list/" not in c.get("/cvd?fy=2569", **VIA_INTERNET).get_data(as_text=True)
    r = c.get("/list/cvd/group?fy=2569&g=in_neither", environ_base=LAN)
    assert r.status_code == 200 and "Z9" in r.get_data(as_text=True)
    assert c.get("/list/cvd/group?g=zzz", environ_base=LAN).status_code == 404
