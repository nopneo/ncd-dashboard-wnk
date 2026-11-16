"""ครอบการดึงข้อมูลแต่ละส่วนของหน้า — ส่วนที่ล้มแสดงข้อผิดพลาดเฉพาะส่วนนั้น ทั้งหน้าไม่ล้ม"""
import logging

log = logging.getLogger("ncd")


def safe(label, fn, *args, **kw):
    """คืนผลของ fn หรือ {"error": "<label>: ดึงข้อมูลไม่ได้"} เมื่อเกิด exception

    บันทึกเฉพาะชนิดของข้อผิดพลาดและชื่อส่วน (ไม่ใส่ค่า/พารามิเตอร์ที่อาจเกี่ยวกับผู้ป่วย)
    """
    try:
        return fn(*args, **kw)
    except Exception as e:      # noqa: BLE001 — ตั้งใจจับทุกอย่างเพื่อไม่ให้หน้าล้ม
        log.warning("section %s failed: %s", label, type(e).__name__)
        return {"error": f"{label}: ดึงข้อมูลไม่ได้"}
