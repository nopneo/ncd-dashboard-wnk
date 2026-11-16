"""ตั้งค่าร่วมของ test — ไม่ต่อฐานข้อมูลจริง (แทน db.fetch ด้วยตัวปลอม)"""
import os
import sys

os.environ["NCD_WARM"] = "0"      # ห้ามเริ่มเธรดอุ่นแคช (ยิงฐาน) ตอน import app ใน test

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402


class FakeDB:
    """บันทึกทุกคำสั่ง SQL และคืนแถวที่ลงทะเบียนไว้ตามข้อความที่พบใน SQL (ตัวแรกที่ตรงชนะ)"""

    def __init__(self):
        self.calls = []        # (sql, args, sql ที่แทนค่าแล้ว)
        self.responses = []    # (ข้อความใน SQL, แถว หรือ Exception)

    def add(self, contains, rows):
        self.responses.append((contains, rows))

    def fetch(self, sql, args=None):
        bound = db._bind(sql, args)      # จับ % ที่ไม่ได้ escape / พารามิเตอร์หาย
        self.calls.append((sql, args, bound))
        for contains, rows in self.responses:
            if contains in bound:
                if isinstance(rows, Exception):
                    raise rows
                return [dict(r) for r in rows]
        return []

    def fetch_one(self, sql, args=None):
        rows = self.fetch(sql, args)
        return rows[0] if rows else {}


@pytest.fixture
def fake_db(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(db, "fetch", f.fetch)
    monkeypatch.setattr(db, "fetch_one", f.fetch_one)
    return f


def pytest_collection_modifyitems(config, items):
    if os.getenv("NCD_LIVE") != "1":
        skip = pytest.mark.skip(reason="ต้องตั้ง NCD_LIVE=1 และต่อฐาน HOSxP ได้")
        for it in items:
            if "live" in it.nodeid.replace("\\", "/").split("/"):
                it.add_marker(skip)


@pytest.fixture(autouse=True)
def _clear_page_cache():
    """แคชหน้าใน app.py ต้องไม่รั่วข้าม test"""
    import pages
    pages.PAGE_CACHE._data.clear()
    yield
    pages.PAGE_CACHE._data.clear()


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    """test ปกติห้ามต่อฐานจริง (ถ้าลืมแทน db.fetch จะล้มทันทีแทนที่จะรอ timeout) — ยกเว้นโหมด live"""
    if os.getenv("NCD_LIVE") == "1":
        return

    def refuse():
        raise RuntimeError("test ห้ามต่อฐานข้อมูลจริง — ใช้ fixture fake_db")

    monkeypatch.setattr(db, "_conn", refuse)


@pytest.fixture(autouse=True)
def _reset_hdc_failure_memory():
    """ความจำการดึง HDC ล้มเหลว/ยังไม่มีข้อมูล (hdc._FAILED, hdc._NOROWS) ต้องไม่รั่วข้าม test"""
    import hdc
    hdc._FAILED.clear()
    hdc._NOROWS.clear()
    yield
    hdc._FAILED.clear()
    hdc._NOROWS.clear()
