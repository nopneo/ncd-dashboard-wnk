"""ช่วงเวลาตามปีงบประมาณ (พ.ศ. 1 ต.ค. – 30 ก.ย.) สำหรับตัวกรองของทุกหน้า"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import List, Mapping, Tuple

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
_QUARTER_START_MONTH = {1: 10, 2: 1, 3: 4, 4: 7}


@dataclass(frozen=True)
class Period:
    fy: int            # ปีงบประมาณ พ.ศ.
    start: date
    end: date
    scope: str         # year | q1..q4 | m1..m12 (เดือนปฏิทิน)
    label: str


def fiscal_year(d: date) -> int:
    return d.year + 543 + (1 if d.month >= 10 else 0)


def fy_bounds(fy: int) -> Tuple[date, date]:
    return date(fy - 544, 10, 1), date(fy - 543, 9, 30)


def _year_of_month(fy: int, month: int) -> int:
    """ปี ค.ศ. ของเดือนปฏิทินที่อยู่ในปีงบ fy"""
    return fy - 544 if month >= 10 else fy - 543


def _be2(year_ce: int) -> str:
    return f"{(year_ce + 543) % 100:02d}"


def _bounds(fy: int, scope: str) -> Tuple[date, date]:
    if scope == "year":
        return fy_bounds(fy)
    if scope.startswith("q"):
        sm = _QUARTER_START_MONTH[int(scope[1])]
        y = _year_of_month(fy, sm)
        start = date(y, sm, 1)
        em = sm + 2
        ey = y + (1 if em > 12 else 0)
        em = em - 12 if em > 12 else em
        return start, date(ey, em, calendar.monthrange(ey, em)[1])
    m = int(scope[1:])
    y = _year_of_month(fy, m)
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _label(fy: int, scope: str, start: date) -> str:
    if scope == "year":
        return f"ปีงบประมาณ {fy}"
    if scope.startswith("q"):
        return f"ไตรมาส {scope[1]} ปีงบ {fy}"
    return f"{THAI_MONTHS[start.month - 1]} {_be2(start.year)}"


def _valid_scope(scope: str) -> bool:
    if scope == "year":
        return True
    if len(scope) == 2 and scope[0] == "q" and scope[1] in "1234":
        return True
    return scope.startswith("m") and scope[1:].isdigit() and 1 <= int(scope[1:]) <= 12


def make(fy: int, scope: str = "year") -> Period:
    start, end = _bounds(fy, scope)
    return Period(fy, start, end, scope, _label(fy, scope, start))


def parse(args: Mapping[str, str], today: date) -> Period:
    """อ่าน fy/scope จาก query string — ค่าผิดรูปแบบใช้ค่าเริ่มต้น (ปีงบปัจจุบัน ทั้งปี)"""
    cur = fiscal_year(today)
    raw = str(args.get("fy", "") or "")
    # isascii: str.isdigit() รับเลขยก/เลขไทย (เช่น "²") แต่ int() แปลงไม่ได้ → 500
    fy = int(raw) if raw.isascii() and raw.isdigit() and 2500 <= int(raw) <= cur else cur       # ไม่รับปีงบอนาคต
    scope = str(args.get("scope", "year") or "year")
    if not (scope.isascii() and _valid_scope(scope)):
        scope = "year"
    elif scope.startswith("m"):
        scope = f"m{int(scope[1:])}"        # m01 / m001 = m1 — ช่วงเดียวกันใช้คีย์แคชเดียว
    return make(fy, scope)


def previous(p: Period) -> Period:
    return make(p.fy - 1, p.scope)


def months(p: Period) -> List[Tuple[date, str]]:
    out, y, m = [], p.start.year, p.start.month
    while date(y, m, 1) <= p.end:
        out.append((date(y, m, 1), f"{THAI_MONTHS[m - 1]} {_be2(y)}"))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def is_partial(p: Period, today: date) -> bool:
    """ช่วงที่เลือกยังไม่สิ้นสุด (ข้อมูลยังมาไม่ครบ) — ร้อยละจึงยังเทียบกับเป้าหมายไม่ได้"""
    return p.end > today


def clip_end(p: Period, today: date) -> date:
    return min(p.end, today)
