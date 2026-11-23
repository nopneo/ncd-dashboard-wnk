"""คนนอก รพ. ไม่เห็นจำนวนเสียชีวิต 1–4 (ย้อนหาได้ว่าใครเสียชีวิตด้วยโรคอะไร) · header จาก proxy ปลอมไม่ได้ ·
/list และ /check ตรวจชื่อโดเมน (กัน DNS rebinding) · /check ทีละครั้ง"""
import threading

import pytest

import app as app_mod
import check
import pages

PUBLIC = {"X-Forwarded-For": "1.2.3.4, 172.70.1.1", "CF-Connecting-IP": "1.2.3.4"}
LAN = {"X-Forwarded-For": "192.168.11.5"}
DATA = {"title": "CVD", "kpis": [
    {"label": "เสียชีวิตใน รพ.", "value": "2", "privacy_n": 2, "unit": "ราย"},
    {"label": "Admit", "value": "40", "unit": "ครั้ง"}],
    "extra": [{"type": "tiles", "items": [{"label": "เสียชีวิตขณะ Admit (มีรหัส CKD)", "value": "7", "privacy_n": 7}]}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pages, "get", lambda key, p, src, opts=None: DATA)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_public_json_hides_small_death_counts(client):
    d = client.get("/api/cvd.json", headers=PUBLIC).get_json()
    assert d["kpis"][0]["value"] == "<5" and d["kpis"][1]["value"] == "40"
    assert d["extra"][0]["items"][0]["value"] == "7"                         # ≥ 5 แสดงตามจริง
    assert "privacy_n" not in str(d)


def test_lan_sees_exact(client):
    d = client.get("/api/cvd.json", headers=LAN).get_json()
    assert d["kpis"][0]["value"] == "2"


def test_public_html_hides_small_death_counts(client):
    html = client.get("/cvd", headers=PUBLIC).get_data(as_text=True)
    assert "&lt;5" in html


def test_public_view_does_not_touch_cache():
    out = app_mod.public_view(DATA)
    assert out["kpis"][0]["value"] == "<5" and DATA["kpis"][0]["value"] == "2" and DATA["kpis"][0]["privacy_n"] == 2


def test_min_cell_zero_disables(monkeypatch):
    monkeypatch.setattr(app_mod, "MIN_CELL", 0)
    assert app_mod.public_view(DATA)["kpis"][0]["value"] == "2"


def test_death_tiles_are_tagged():
    import inspect
    from queries import ckd, cvd
    assert '"privacy_n": sd["deaths"]' in inspect.getsource(ckd._indicators)
    assert '"privacy_n": core["deaths"]' in inspect.getsource(cvd._kpis)


# ------------------------------------------------------------------ header จาก proxy

def test_prefix_only_from_trusted_proxy():
    probe = app_mod.app.test_client()
    lan_peer = probe.get("/ncd/healthz", headers={"X-Forwarded-Prefix": "/ncd"}, environ_base={"REMOTE_ADDR": "192.168.1.9"})
    assert lan_peer.status_code == 404                                       # ไม่เชื่อ prefix จากเครื่องอื่น
    assert probe.get("/ncd/healthz", headers={"X-Forwarded-Prefix": "/ncd"}).status_code == 200   # 127.0.0.1


def test_bad_prefix_ignored(client):
    html = client.get("/cvd", headers={"X-Forwarded-Prefix": "//evil.example"}).get_data(as_text=True)
    assert "//evil.example" not in html


# ------------------------------------------------------------------ ช่วง IP / โดเมน

@pytest.mark.parametrize("ip, lan", [("192.168.1.1", True), ("10.0.0.1", True), ("127.0.0.1", True), ("::1", True),
                                     ("203.0.113.7", False), ("198.18.0.1", False), ("8.8.8.8", False),
                                     ("::ffff:192.168.1.1", True), ("::ffff:8.8.8.8", False)])
def test_is_lan_explicit_ranges(ip, lan):
    assert check.is_lan(ip) is lan


def test_allowed_hosts_for_list_and_check(client, monkeypatch, fake_db):
    monkeypatch.setenv("NCD_ALLOWED_HOSTS", "lan.wnkhos.go.th")
    monkeypatch.setattr(check, "audit", lambda p: [])
    bad = client.get("/check", headers=LAN, base_url="http://evil.example")
    good = client.get("/check", headers=LAN, base_url="https://lan.wnkhos.go.th")
    assert bad.status_code == 403 and good.status_code == 200
    assert client.get("/list/ht/miss", headers=LAN, base_url="http://evil.example").status_code == 403
    assert client.get("/cvd", base_url="http://evil.example").status_code == 200     # หน้าสรุปไม่จำกัดโดเมน


def test_check_runs_one_at_a_time(client, monkeypatch):
    monkeypatch.setattr(check, "audit", lambda p: [])
    assert app_mod._check_lock.acquire(blocking=False)
    try:
        assert client.get("/check", headers=LAN).status_code == 503
    finally:
        app_mod._check_lock.release()
    assert client.get("/check", headers=LAN).status_code == 200
