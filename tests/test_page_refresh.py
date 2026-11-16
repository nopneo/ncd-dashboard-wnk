"""สลับหน้า/โรคแล้วต้องไม่รอสร้างข้อมูลใหม่: แคชหมดอายุ → ส่งของเดิมทันทีแล้วรีเฟรชเบื้องหลัง,
คำขอซ้ำขณะกำลังสร้างต้องรอผลเดียวกัน (ไม่ยิงฐานซ้ำ), และอุ่นแคชหน้าเริ่มต้นล่วงหน้า"""
import threading
import time

import pytest

import pages
import periods


class Builder:
    """ตัวสร้างหน้าปลอม: นับจำนวนครั้งที่ถูกเรียก · gate ใช้หน่วงให้ทดสอบจังหวะรีเฟรช"""

    def __init__(self, value="v1", delay=0.0, gate=None, fail=False):
        self.value, self.delay, self.gate, self.fail = value, delay, gate, fail
        self.calls = 0

    def __call__(self, p, src="hosxp", opts=None):
        self.calls += 1
        if self.gate is not None:
            assert self.gate.wait(5), "gate ไม่ถูกปล่อย"
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("ฐานล่ม")
        return {"title": "ทดสอบ", "kpis": [{"label": "x", "value": self.value}]}


@pytest.fixture
def reg(monkeypatch):
    monkeypatch.setattr(pages, "REGISTRY", {})
    monkeypatch.setattr(pages, "_locks", {})
    return pages.REGISTRY


def _age_all(seconds):
    for k, (t, v) in list(pages.PAGE_CACHE._data.items()):
        pages.PAGE_CACHE._data[k] = (t - seconds, v)


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _value(d):
    return d["kpis"][0]["value"]


def test_expired_cache_is_served_at_once_and_refreshed_in_background(reg):
    gate = threading.Event()
    b = Builder("v1")
    reg["ht"] = b
    p = periods.make(2569)
    assert _value(pages.get("ht", p)) == "v1"
    _age_all(pages.CACHE_TTL + 5)               # หมดอายุแต่ยังไม่เกิน STALE_MAX
    b.value, b.gate = "v2", gate                # รอบรีเฟรชจะค้างที่ gate
    t0 = time.time()
    assert _value(pages.get("ht", p)) == "v1"   # ได้ของเดิมทันที ไม่รอ builder
    assert time.time() - t0 < 1.0
    gate.set()
    assert _wait(lambda: b.calls == 2 and _value(pages.get("ht", p)) == "v2")


def test_concurrent_cold_requests_build_once(reg):
    b = Builder(delay=0.3)
    reg["dm"] = b
    p = periods.make(2569)
    out = []
    ts = [threading.Thread(target=lambda: out.append(pages.get("dm", p))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert b.calls == 1
    assert len(out) == 4 and all(_value(d) == "v1" for d in out)


def test_failed_refresh_keeps_serving_old_data(reg):
    b = Builder("v1")
    reg["ckd"] = b
    p = periods.make(2569)
    pages.get("ckd", p)
    _age_all(pages.CACHE_TTL + 5)
    b.fail = True
    assert _value(pages.get("ckd", p)) == "v1"
    assert _wait(lambda: b.calls == 2)
    time.sleep(0.1)
    assert _value(pages.get("ckd", p)) == "v1"  # ยังเป็นของเดิม ไม่ถูกทับด้วยหน้า error


def test_too_old_cache_is_rebuilt_synchronously(reg):
    b = Builder("v1")
    reg["cvd"] = b
    p = periods.make(2569)
    pages.get("cvd", p)
    _age_all(pages.STALE_MAX + 5)               # เก่าเกินกว่าจะแสดง → สร้างใหม่ก่อนตอบ
    b.value = "v2"
    assert _value(pages.get("cvd", p)) == "v2"
    assert b.calls == 2


def test_warm_prebuilds_every_default_page(reg):
    builders = {k: Builder(k) for k in pages.KEYS}
    reg.update(builders)
    fy = periods.fiscal_year(pages.today())
    pages.warm([fy])
    assert all(b.calls == 1 for b in builders.values())
    for k in pages.KEYS:                        # หลังอุ่นแล้ว เปิดหน้าไม่ต้องสร้างซ้ำ
        pages.get(k, periods.make(fy))
    assert all(b.calls == 1 for b in builders.values())


def test_warm_skips_a_page_that_fails_and_continues(reg):
    builders = {k: Builder(k) for k in pages.KEYS}
    builders["dm"].fail = True
    reg.update(builders)
    pages.warm([periods.fiscal_year(pages.today())])
    assert builders["cvd"].calls == 1 and builders["dm"].calls == 1


def test_warm_cycle_also_prebuilds_hdc_for_current_year(reg):
    seen = []

    def make(k):
        def b(p, src="hosxp", opts=None):
            seen.append((k, p.fy, src))
            return {"title": k}
        return b

    reg.update({k: make(k) for k in pages.KEYS})
    pages.warm_cycle(2570, first=True)
    assert ("ht", 2570, "hosxp") in seen and ("ht", 2569, "hosxp") in seen     # รอบแรกอุ่นปีก่อนด้วย
    assert ("ht", 2570, "hdc") in seen                                          # สลับไป HDC ไม่ต้องรอดึง
    assert ("ht", 2569, "hdc") not in seen
    seen.clear()
    pages.warm_cycle(2570, first=False)
    assert not any(fy == 2569 for _k, fy, _s in seen)


def test_warm_cycle_never_calls_hdc_api(reg, monkeypatch):
    monkeypatch.setattr(pages.hdc, "sync", lambda *a, **k: pytest.fail("การดึง HDC ต้องอยู่เธรดของตัวเอง ไม่ปนกับการอุ่นหน้า"))
    reg.update({k: (lambda p, src="hosxp", opts=None: {"title": "x"}) for k in pages.KEYS})
    pages.warm_cycle(2570, first=True)


def test_sync_hdc_covers_current_and_previous_year_on_first_run(monkeypatch):
    synced = []
    monkeypatch.setattr(pages.hdc, "sync", lambda fy, tables=None: (synced.append(fy), {"ok": [], "failed": []})[1])
    pages.sync_hdc(2570, first=True)
    assert synced == [2570, 2569]
    synced.clear()
    pages.sync_hdc(2570)
    assert synced == [2570]


def test_sync_hdc_continues_with_next_year_after_a_crash(monkeypatch):
    synced = []

    def sync(fy, tables=None):
        synced.append(fy)
        if fy == 2570:
            raise RuntimeError("hdc ล่ม")
        return {"ok": [], "failed": []}

    monkeypatch.setattr(pages.hdc, "sync", sync)
    pages.sync_hdc(2570, first=True)
    assert synced == [2570, 2569]


def test_hdc_syncer_thread_keeps_running_after_errors(monkeypatch):
    monkeypatch.setattr(pages, "_syncer", None)
    calls = []

    def sync(fy, tables=None):
        calls.append(fy)
        if len(calls) == 1:
            raise RuntimeError("ล่มรอบแรก")
        return {"ok": [], "failed": []}

    monkeypatch.setattr(pages.hdc, "sync", sync)
    t = pages.start_hdc_syncer(interval=0.02)
    try:
        assert _wait(lambda: len(calls) >= 4)                                   # ล้มครั้งเดียวแล้วเธรดยังวนต่อ
        assert t.is_alive() and pages.start_hdc_syncer() is t                   # เรียกซ้ำไม่สร้างเธรดใหม่
    finally:
        t.stop_event.set()
        t.join(2)
    assert not t.is_alive()


def test_page_warmer_thread_keeps_running_after_errors(monkeypatch):
    monkeypatch.setattr(pages, "_warmer", None)
    calls = []

    def cycle(fy, first=False):
        calls.append(first)
        if len(calls) == 1:
            raise RuntimeError("ฐานล่มรอบแรก")

    monkeypatch.setattr(pages, "warm_cycle", cycle)
    t = pages.start_warmer(interval=0.02)
    try:
        assert _wait(lambda: len(calls) >= 3) and t.is_alive()
    finally:
        t.stop_event.set()
        t.join(2)
    assert not t.is_alive()
