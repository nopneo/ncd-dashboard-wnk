"""รายการหน้าและตัวสร้างข้อมูลของแต่ละหน้า

รูปแบบ dict ที่ build(p, src, opts) คืน (ทุกส่วนเป็นทางเลือก และอาจเป็น {"error": ...}):
  title, subtitle, as_of
  kpis    : [{label, value, sub, delta{pct,dir}, tone, icon}]
  monthly : {labels, series: [{name, values, color}]}
  donut   : {title, center, total_label, parts: [(ป้าย, ค่า, สี)]}
  table / recent : {title, columns, rows}   (เซลล์เป็นข้อความ หรือ {text, chip: ok|warn|bad})
  notes   : [{tone: info|ok|warn, text}]
  extra   : [{type: tiles, title, items: [{label, value, sub, tone, icon}]} | {type: table, ...}]
"""
import importlib
import logging
import os
import threading
import time
from datetime import date

import hdc
import periods
import sections
import ui
from cache import TTLCache

NAV = [
    {"key": "overview", "title": "ภาพรวม NCD", "icon": "layout-dashboard"},
    {"key": "ht", "title": "ความดันโลหิตสูง (HT)", "icon": "activity"},
    {"key": "dm", "title": "เบาหวาน (DM)", "icon": "droplet"},
    {"key": "ckd", "title": "ไตเรื้อรัง (CKD)", "icon": "bean"},
    {"key": "warfarin", "title": "วาร์ฟาริน (Warfarin)", "icon": "pill"},
    {"key": "copd", "title": "COPD / หืด", "icon": "wind"},
    {"key": "cvd", "title": "หลอดเลือดสมอง/หัวใจ (CVD)", "icon": "heart-pulse"},
]
KEYS = [n["key"] for n in NAV]

#: แคชผลของหน้า (คีย์ = หน้า+ตัวกรอง) — query ฐาน HOSxP ใช้เวลาหลายวินาที · ผลที่มีส่วนล้มไม่ถูกแคช
PAGE_CACHE = TTLCache(maxsize=64)
#: อายุข้อมูล "สด" — เลยแล้วยังแสดงของเดิมได้ทันทีแล้วรีเฟรชเบื้องหลัง (ผู้ใช้ไม่ต้องรอตอนสลับหน้า)
CACHE_TTL = int(os.getenv("NCD_CACHE_TTL", "900"))
#: เก่าเกินนี้ (วินาที) ไม่แสดงของเดิมอีก → สร้างใหม่ก่อนตอบ (กันข้อมูลค้างนานเมื่อรีเฟรชล้มต่อเนื่อง)
STALE_MAX = int(os.getenv("NCD_STALE_MAX", "21600"))
WARM_INTERVAL = int(os.getenv("NCD_WARM_INTERVAL", "600"))
HDC_SYNC_INTERVAL = int(os.getenv("NCD_HDC_SYNC_INTERVAL", "3600"))   # ตรวจทุกชั่วโมงว่าถึงรอบดึงวันละครั้งหรือยัง
_log = logging.getLogger("ncd.pages")
_guard = threading.Lock()
_locks = {}                 # คีย์แคช → lock: คำขอที่มาพร้อมกัน/กำลังรีเฟรช สร้างหน้าเดียวกันครั้งเดียว
_warmer = None
_syncer = None

#: key → build(p, src="hosxp", opts=None) — เติมโดย load() จากโมดูล queries/<key>.py
REGISTRY = {}


def load():
    """นำเข้าโมดูล queries/<key>.py เท่าที่มีอยู่แล้ว (โมดูลที่ยังไม่ถูกสร้างจะถูกข้าม)"""
    for key in KEYS:
        try:
            REGISTRY[key] = importlib.import_module("queries." + key).build
        except ModuleNotFoundError as e:
            if e.name not in ("queries", "queries." + key):
                raise


def title_of(key):
    return next(n["title"] for n in NAV if n["key"] == key)


def has_error(v) -> bool:
    """มีส่วนใดส่วนหนึ่งเป็น {"error": ...} หรือ page_error (ไม่แคชผลที่ไม่สมบูรณ์)"""
    if isinstance(v, dict):
        return "error" in v or "page_error" in v or bool(v.get("incomplete")) or any(has_error(x) for x in v.values())
    if isinstance(v, list):
        return any(has_error(x) for x in v)
    return False


def today() -> date:
    return date.today()


def _neutral(v):
    """ช่วงที่ยังไม่จบ: ป้ายผ่าน/ไม่ผ่านเทียบเป้าเปลี่ยนเป็น "ยังไม่ครบช่วง" (คงป้าย "ไม่มีข้อมูล" ไว้) และตัดข้อสังเกตที่เทียบเป้า"""
    if isinstance(v, list):
        return [_neutral(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "chip" in v and v.get("text") != "ไม่มีข้อมูล":
        return {"text": "ยังไม่ครบช่วง", "chip": "warn"}
    out = {k: _neutral(x) for k, x in v.items()}
    if isinstance(out.get("notes"), list):      # ข้อสังเกตที่เทียบกับเป้าหมาย ("ต่ำกว่าเป้า ...") ตัดออก ที่เหลือคงไว้
        out["notes"] = [n for n in out["notes"] if not (isinstance(n, dict) and "ต่ำกว่าเป้า" in str(n.get("text", "")))]
    return out


#: ตัวเลือกที่หน้าแต่ละหน้าอ่านจริง → ค่าที่รับได้ (นอกนั้นตัดทิ้งก่อนทำคีย์แคช)
#: เดิมคีย์แคชรวม query string ทุกตัว → ?x=1, ?x=2 … ทำให้แคชพลาดทุกครั้ง ยิงฐานซ้ำ ไล่หน้าที่อุ่นไว้ออก และ _locks โตไม่หยุด
PAGE_OPTS = {"copd": {"grp": ("copd", "asthma")}}      # grp=all = ค่าเริ่มต้น (ไม่ใส่ในคีย์)


def clean_opts(key, opts) -> dict:
    """เหลือเฉพาะตัวเลือกที่หน้านี้ใช้และค่าถูกต้อง — ทำให้คีย์แคชมีจำนวนจำกัด"""
    allowed = PAGE_OPTS.get(key, {})
    return {k: v for k, v in (opts or {}).items() if k in allowed and v in allowed[k]}


def _cache_key(key, p, src, opts):
    return (key, p.fy, p.scope, src, tuple(sorted(opts.items())))


def _lock_for(ck):
    with _guard:
        return _locks.setdefault(ck, threading.Lock())


def _compute(ck, key, p, src, opts) -> dict:
    """สร้างหน้าจากฐานจริง แล้วแคชถ้าสมบูรณ์ (ผลที่มีส่วนล้มไม่ถูกแคช จึงไม่ทับของเดิมที่ยังดี)"""
    builder = REGISTRY.get(key)
    if builder is None:
        data = {"title": title_of(key), "page_error": "หน้านี้ยังไม่พร้อมใช้งาน"}
    else:
        data = sections.safe(title_of(key), builder, p, src, opts)
        if set(data) == {"error"}:
            data = {"title": title_of(key), "page_error": data["error"]}
    data.setdefault("title", title_of(key))
    now = today()
    if periods.is_partial(p, now) and not has_error(data):
        data = _neutral(data)
        data["partial_notice"] = (f"ช่วง {p.label} ยังไม่สิ้นสุด — ข้อมูลถึงวันที่ {ui.thai_date(now)} ร้อยละอาจต่ำกว่าเมื่อสิ้นช่วง "
                                  "จึงยังไม่เทียบกับเป้าหมาย")
    if not has_error(data):
        PAGE_CACHE.set(ck, data)
    return data


def _refresh_async(ck, key, p, src, opts):
    lk = _lock_for(ck)
    if not lk.acquire(blocking=False):      # มีคนกำลังสร้าง/รีเฟรชหน้านี้อยู่แล้ว
        return

    def run():
        try:
            _compute(ck, key, p, src, opts)
        except Exception:       # noqa: BLE001 — รีเฟรชเบื้องหลังล้ม: คงของเดิมไว้
            _log.exception("รีเฟรชหน้า %s ไม่สำเร็จ", key)
        finally:
            lk.release()

    threading.Thread(target=run, name=f"ncd-refresh-{key}", daemon=True).start()


def get(key: str, p, src: str = "hosxp", opts=None) -> dict:
    """ข้อมูลของหน้า key (แคชแล้ว) — ล้มเหลวคืน {"title", "page_error"} ไม่ throw
    สด → คืนทันที · หมดอายุแต่ยังไม่เกิน STALE_MAX → คืนของเดิมทันทีแล้วรีเฟรชเบื้องหลัง · ไม่มี/เก่าเกิน → สร้างก่อนตอบ (คำขอซ้ำรอผลเดียวกัน)"""
    opts = clean_opts(key, opts)
    ck = _cache_key(key, p, src, opts)
    cached = PAGE_CACHE.get(ck, CACHE_TTL)
    if cached is not None:
        return cached
    stale = PAGE_CACHE.get_stale(ck)
    if stale is not None and time.time() - stale[0] < STALE_MAX:
        _refresh_async(ck, key, p, src, opts)
        return stale[1]
    with _lock_for(ck):
        cached = PAGE_CACHE.get(ck, CACHE_TTL)      # คนที่มาก่อนอาจสร้างเสร็จระหว่างรอ lock
        if cached is not None:
            return cached
        return _compute(ck, key, p, src, opts)


def warm(fys, src: str = "hosxp"):
    """สร้างหน้าเริ่มต้น (ทั้งปีงบ) ของทุกโรคล่วงหน้า — หน้าภาพรวมไว้ท้ายสุดเพราะหนักสุด · หน้าไหนล้มข้ามไปหน้าถัดไป"""
    for fy in fys:
        for key in [k for k in KEYS if k != "overview"] + ["overview"]:
            try:
                get(key, periods.make(fy), src, {})
            except Exception:       # noqa: BLE001
                _log.exception("อุ่นแคชหน้า %s ปี %s ไม่สำเร็จ", key, fy)


def warm_cycle(fy, first=False):
    """หนึ่งรอบอุ่นแคช: HOSxP ปีงบปัจจุบัน (+ปีก่อนหน้าเฉพาะรอบแรก) และหน้า HDC ปีงบปัจจุบัน (สร้างจากแคชไฟล์ที่ sync_hdc ดึงไว้
    ให้ปุ่มสลับ HDC ไม่ต้องรอ) — ไม่เรียก API ของ HDC ที่นี่ (อยู่เธรด ncd-hdc-sync แยก กันหน้าค้างแล้วลากการดึง HDC ค้างตาม)"""
    warm([fy, fy - 1] if first else [fy])
    warm([fy], "hdc")


def sync_hdc(fy, first=False):
    """ดึง HDC เข้าแคชไฟล์ (hdc.sync ดึงจริงวันละครั้ง) — รอบแรกทั้งปีงบปัจจุบันและปีก่อนหน้า · ปีไหนล้มข้ามไปปีถัดไป"""
    for y in ([fy, fy - 1] if first else [fy]):
        try:
            res = hdc.sync(y)
            if res["ok"] or res["failed"]:
                _log.info("HDC sync ปี %s: %s", y, {k: len(v) for k, v in res.items() if v})
        except Exception:       # noqa: BLE001 — ดึง HDC ล้ม: ใช้แคชเดิมต่อ
            _log.exception("HDC sync ปี %s ไม่สำเร็จ", y)


def start_hdc_syncer(interval: float = None):
    """เธรดเบื้องหลังแยกต่างหาก: ตรวจทุก interval วินาที (ค่าเริ่มต้น 1 ชม.) ว่าข้อมูล HDC ถึงกำหนดดึงรอบวันหรือยัง —
    ถ้ายังใหม่ก็ไม่เรียก API · ข้อผิดพลาดทุกชนิดถูกจับ เธรดไม่ตาย"""
    global _syncer
    with _guard:
        if _syncer is not None:
            return _syncer
        every = interval or HDC_SYNC_INTERVAL

        stop = threading.Event()

        def loop():
            first = True
            while not stop.is_set():
                try:
                    sync_hdc(periods.fiscal_year(today()), first)
                except Exception:       # noqa: BLE001
                    _log.exception("เธรด HDC sync สะดุด")
                first = False
                stop.wait(every)

        _syncer = threading.Thread(target=loop, name="ncd-hdc-sync", daemon=True)
        _syncer.stop_event = stop       # ให้ test หยุดเธรดได้ (production ไม่เรียก)
        _syncer.start()
        return _syncer


def start_warmer(interval: int = None):
    """เธรดเบื้องหลัง: อุ่นแคชทันทีที่เริ่ม แล้วรีเฟรชปีงบปัจจุบันทุก interval วินาที (ปีก่อนหน้าอุ่นครั้งเดียวตอนเริ่ม)"""
    global _warmer
    with _guard:
        if _warmer is not None:
            return _warmer
        every = interval or WARM_INTERVAL

        stop = threading.Event()

        def loop():
            first = True
            while not stop.is_set():
                try:
                    warm_cycle(periods.fiscal_year(today()), first)
                except Exception:       # noqa: BLE001 — รอบไหนล้ม รอบหน้าลองใหม่ ไม่ปล่อยเธรดตาย
                    _log.exception("รอบอุ่นแคชสะดุด")
                first = False
                stop.wait(every)

        _warmer = threading.Thread(target=loop, name="ncd-warmer", daemon=True)
        _warmer.stop_event = stop       # ให้ test หยุดเธรดได้ (production ไม่เรียก)
        _warmer.start()
        return _warmer
