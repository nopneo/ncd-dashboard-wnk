"""ตรรกะแบ่งกลุ่มทางคลินิก — ฟังก์ชันบริสุทธิ์ ไม่แตะฐานข้อมูล

ใช้ร่วมโดยหน้า HT/DM/CKD/Warfarin/CVD · เกณฑ์ที่ปรับได้อ่านจาก config (env)
"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Tuple

import config

_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_HEAD = re.compile(r"^[<>]?\s*(\d[\d,]*(?:\.\d+)?)(.*)$")
#: ส่วนต่อท้ายที่ยอมรับหลังตัวเลข: คำอธิบายในวงเล็บ [..] (..) หรือหน่วย/ธง เช่น "mg/dl", "%", "H" (ติดตัวเลขได้ เช่น 6.5% 9.2H)
_SUFFIX = re.compile(r"^(?:\s*[\[(].*|\s*[A-Za-z%/µ].*)?$")
_EXPONENT = re.compile(r"^[eE][+-]?\d")


def parse_result(text, allow_zero: bool = False) -> Optional[float]:
    """แปลงผล lab ที่อาจเป็นข้อความเป็นตัวเลข

    "<5.0"/">90" ใช้ค่าขอบ · "1,234.5" คือหลักพัน · "7,2" ไม่เดาจุดทศนิยม (None) · ว่าง/ข้อความอื่น → None
    ยอมรับคำอธิบาย/หน่วยต่อท้าย เช่น "90.58 [Stage 1]" (eGFR ก่อน ธ.ค. 2568 ของ รพ.วังน้ำเขียว), "5.2 mg/dl"
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = _HEAD.match(str(text).strip())
    if not m or not _SUFFIX.match(m.group(2)) or _EXPONENT.match(m.group(2)):
        return None
    head = m.group(1)
    if "," in head:
        if not _THOUSANDS.match(head):
            return None
        head = head.replace(",", "")
    try:
        v = float(head)
    except ValueError:
        return None
    # 0 = ค่าที่กรอกแทนว่างสำหรับ HbA1c/INR/eGFR/LDL (ไม่มีค่าศูนย์จริง) · แต่ Microalbumin/UACR ศูนย์เป็นผลจริง → allow_zero=True
    return v if (v > 0 or (allow_zero and v == 0)) else None


def valid_bp(sbp, dbp) -> bool:
    """ค่าความดันที่เป็นไปได้ทางสรีรวิทยา (กันค่า 0/999 จากการกรอกผิด)"""
    try:
        return 60 <= float(sbp) <= 300 and 30 <= float(dbp) <= 200 and float(sbp) > float(dbp)
    except (TypeError, ValueError):
        return False


def bp_group(sbp, dbp) -> Optional[str]:
    if not valid_bp(sbp, dbp):
        return None
    if sbp >= 160 or dbp >= 100:
        return "uncontrolled"
    if sbp < 140 and dbp < 90:
        return "controlled"
    return "partial"


def hba1c_group(v) -> Optional[str]:
    if v is None:
        return None
    if v < 7:
        return "lt7"
    return "7to79" if v < 8 else "ge8"


def inr_group(v, low: float = None, high: float = None) -> Optional[str]:
    if v is None:
        return None
    low = config.INR_LOW if low is None else low
    high = config.INR_HIGH if high is None else high
    if v < low:
        return "low"
    return "in" if v <= high else "high"


def ckd_stage(egfr) -> Optional[str]:
    if egfr is None:
        return None
    if egfr >= 60:
        return "G1-2"
    if egfr >= 45:
        return "G3a"
    if egfr >= 30:
        return "G3b"
    if egfr >= 15:
        return "G4"
    return "G5"


def egfr_slope_per_year(points: List[Tuple[date, float]]) -> Optional[float]:
    """ความชันของ eGFR (หน่วยต่อปี) ด้วย least squares · น้อยกว่า 2 จุดหรือวันเดียวกัน → None"""
    pts = sorted(points)
    if len(pts) < 2:
        return None
    d0 = pts[0][0]
    xs = [(d - d0).days / 365.25 for d, _ in pts]
    ys = [v for _, v in pts]
    n = len(pts)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def ttr_rosendaal(points: List[Tuple[date, float]], low: float, high: float) -> Optional[float]:
    """Time in Therapeutic Range (%) — ประมาณค่า INR เชิงเส้นรายวันระหว่างผลสองครั้งติดกัน (Rosendaal)"""
    pts = sorted(points)
    if len(pts) < 2:
        return None
    in_range = total = 0
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        days = (d1 - d0).days
        for t in range(max(days, 0)):
            v = v0 + (v1 - v0) * t / days
            total += 1
            if low - 1e-9 <= v <= high + 1e-9:
                in_range += 1
    return round(100.0 * in_range / total, 1) if total else None
