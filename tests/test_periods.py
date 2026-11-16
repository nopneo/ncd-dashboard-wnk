from datetime import date

import periods
from periods import clip_end, fiscal_year, fy_bounds, months, parse, previous

TODAY = date(2026, 11, 11)


def test_fiscal_year_boundaries():
    assert fiscal_year(date(2026, 10, 1)) == 2570
    assert fiscal_year(date(2026, 9, 30)) == 2569


def test_fy_bounds():
    assert fy_bounds(2569) == (date(2025, 10, 1), date(2026, 9, 30))


def test_default_is_current_fiscal_year():
    p = parse({}, TODAY)
    assert (p.fy, p.scope) == (2570, "year")
    assert p.start == date(2026, 10, 1) and p.end == date(2027, 9, 30)


def test_invalid_args_fall_back_to_default():
    assert parse({"fy": "abc"}, TODAY).fy == 2570
    assert parse({"fy": "1999"}, TODAY).fy == 2570
    assert parse({"scope": "zzz"}, TODAY).scope == "year"


def test_quarter_scope():
    p = parse({"fy": "2569", "scope": "q1"}, TODAY)
    assert (p.start, p.end) == (date(2025, 10, 1), date(2025, 12, 31))
    p4 = parse({"fy": "2569", "scope": "q4"}, TODAY)
    assert (p4.start, p4.end) == (date(2026, 7, 1), date(2026, 9, 30))


def test_month_scope_is_calendar_month_within_fiscal_year():
    p = parse({"fy": "2569", "scope": "m11"}, TODAY)      # พ.ย. 2025 อยู่ในปีงบ 2569
    assert (p.start, p.end) == (date(2025, 11, 1), date(2025, 11, 30))
    p2 = parse({"fy": "2569", "scope": "m2"}, TODAY)      # ก.พ. 2026
    assert (p2.start, p2.end) == (date(2026, 2, 1), date(2026, 2, 28))


def test_months_year_has_twelve_with_thai_labels():
    ms = months(parse({"fy": "2569"}, TODAY))
    assert len(ms) == 12
    assert ms[0] == (date(2025, 10, 1), "ต.ค. 68")
    assert ms[-1] == (date(2026, 9, 1), "ก.ย. 69")


def test_months_of_quarter_and_month():
    assert len(months(parse({"fy": "2569", "scope": "q2"}, TODAY))) == 3
    assert len(months(parse({"fy": "2569", "scope": "m11"}, TODAY))) == 1


def test_previous_is_prior_fiscal_year_same_scope():
    p = previous(parse({"scope": "q1"}, TODAY))
    assert (p.fy, p.scope, p.start) == (2569, "q1", date(2025, 10, 1))


def test_clip_end_never_beyond_today():
    assert clip_end(parse({}, TODAY), TODAY) == TODAY
    assert clip_end(parse({"fy": "2569"}, TODAY), TODAY) == date(2026, 9, 30)


def test_label_mentions_fiscal_year():
    assert "2570" in parse({}, TODAY).label
    assert periods.__doc__
