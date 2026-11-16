"""ตัวช่วยแสดงผล — คำนวณร้อยละ/รูปแบบตัวเลข และข้อมูลสำหรับวาดกราฟ SVG/CSS ฝั่งเซิร์ฟเวอร์"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

DASH = "—"
_TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def thai_date(d) -> str:
    """30 ก.ย. 2569"""
    return f"{d.day} {_TH_MONTHS[d.month - 1]} {d.year + 543}"


def pct(num, den) -> Optional[float]:
    """ร้อยละ 1 ตำแหน่ง · ตัวหารเป็น 0/None → None (ไม่หารศูนย์)"""
    if num is None or not den:
        return None
    return round(100.0 * num / den, 1)


def fmt_pct(v) -> str:
    return DASH if v is None else f"{v:.1f}%"


def fmt_int(v) -> str:
    return DASH if v is None else f"{int(round(v)):,}"


def fmt_per100k(num, pop) -> str:
    """อัตราต่อแสนประชากร 1 ตำแหน่ง · ไม่มีประชากร → —"""
    if num is None or not pop:
        return DASH
    return f"{100000.0 * num / pop:,.1f}"


def target_chip(value, target):
    """ป้ายสถานะเทียบเป้า (ร้อยละ ≥ เป้า = ผ่าน) · ไม่มีเป้า → "" (ไม่ตัดสิน)"""
    if target is None:
        return ""
    if value is None:
        return {"text": "ไม่มีข้อมูล", "chip": "warn"}
    return {"text": "ผ่าน", "chip": "ok"} if value >= target else {"text": "ต่ำกว่าเป้า", "chip": "bad"}


def delta(cur, prev) -> dict:
    """เทียบกับปีก่อน: {"pct": ร้อยละการเปลี่ยนแปลง|None, "dir": up|down|flat}"""
    if cur is None or not prev:
        return {"pct": None, "dir": "flat"}
    p = round(100.0 * (cur - prev) / prev, 1)
    return {"pct": p, "dir": "up" if p > 0 else "down" if p < 0 else "flat"}


def donut_segments(parts: List[Tuple[str, float, str]]) -> list:
    """ส่วนของโดนัท SVG (วงกลม r=15.9155 เส้นรอบวง = 100) เริ่มที่ 12 นาฬิกา · ผลรวมศูนย์ → []"""
    total = sum(v for _, v, _ in parts)
    if total <= 0:
        return []
    out, cum = [], 0.0
    for label, value, color in parts:
        p = round(100.0 * value / total, 1)
        out.append({"label": label, "value": value, "color": color, "pct": p,
                    "dash": f"{p} {round(100 - p, 1)}", "offset": 25 - cum})
        cum += p
    return out


_STEPS = (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)


def nice_max(v) -> float:
    """เพดานแกนที่ปัดให้สวย (1200 สำหรับ 1188)"""
    if not v or v <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(v))
    for s in _STEPS:
        if v <= s * mag:
            top = s * mag
            return int(top) if top == int(top) else top
    return 10 * mag


def bar_geometry(monthly: dict) -> dict:
    """ข้อมูลแท่งกราฟรายเดือน: ความสูงเป็น % ของเพดาน · ค่า None = ไม่มีข้อมูล (สูง 0)"""
    labels, series = monthly["labels"], monthly["series"]
    top = nice_max(max([v for s in series for v in s["values"] if v is not None] or [0]))
    groups = []
    for i, label in enumerate(labels):
        bars = []
        for s in series:
            v = s["values"][i] if i < len(s["values"]) else None
            bars.append({"name": s["name"], "color": s["color"], "value": v,
                         "height": 0 if v is None else 100.0 * v / top})
        groups.append({"label": label, "bars": bars})
    return {"max": top, "groups": groups,
            "ticks": [round(top * k / 4) for k in range(4, -1, -1)]}
