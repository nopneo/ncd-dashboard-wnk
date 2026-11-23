"""NCD Dashboard — แดชบอร์ดกลุ่มโรคไม่ติดต่อเรื้อรัง (HT DM CKD Warfarin COPD/หืด CVD)

รันเอง:      python app.py            → http://127.0.0.1:5400/
production:  gunicorn -b 127.0.0.1:<PORT> app:app หลัง Apache (sub-path ด้วย X-Forwarded-Prefix) — ห้ามเปิด 0.0.0.0
"""
import copy
import mimetypes
import logging
import os
import re
import threading
from datetime import date
from urllib.parse import urlencode

from flask import Flask, abort, jsonify, make_response, render_template, request, url_for
from markupsafe import Markup

import check
import db
import pages
import periods
import ui
from queries import ckd, clinic_lists, remission, remission_claim


def _dm_list(p, ind, g):
    if ind == "remission":
        return remission.patient_list(p, ind, g)
    if ind == "claim":
        return remission_claim.patient_list(p, ind, g)
    return clinic_lists.patient_list("dm", p, ind, g)


#: หน้าที่มีรายชื่อผู้ป่วย (เปิดเฉพาะ LAN) → ฟังก์ชัน (p, ind, g) → dict · รายการที่ไม่รู้จักยก KeyError
LIST_PAGES = {"ckd": ckd.patient_list, "dm": _dm_list,
              "ht": lambda p, ind, g: clinic_lists.patient_list("ht", p, ind, g),
              "copd": lambda p, ind, g: clinic_lists.patient_list("copd", p, ind, g,
                                                                  **pages.clean_opts("copd", {"grp": request.args.get("grp")})),
              "cvd": lambda p, ind, g: clinic_lists.patient_list("cvd", p, ind, g),
              "warfarin": lambda p, ind, g: clinic_lists.patient_list("warfarin", p, ind, g)}

# Windows บางเครื่องตั้ง registry .css = text/plain → Chrome ไม่ใช้ stylesheet
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/javascript", ".js")

VERSION = "0.1.11"
HERE = os.path.dirname(os.path.abspath(__file__))


#: reverse proxy ที่เชื่อ X-Forwarded-Prefix / X-Forwarded-Proto ได้ (Apache บนเครื่องเดียวกัน)
TRUSTED_PROXIES = {x.strip() for x in os.getenv("NCD_TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if x.strip()}
#: คนนอก รพ. เห็นจำนวนเสียชีวิต 1..MIN_CELL-1 เป็น "<MIN_CELL" · 0 = ปิด
MIN_CELL = max(int(os.getenv("NCD_PUBLIC_MIN_CELL", "5") or 0), 0)


def public_view(data):
    """สำเนาข้อมูลหน้า (ต้นฉบับอยู่ในแคชที่ใช้ร่วมกับเครื่องใน รพ. — ห้ามแก้) ที่ซ่อนช่องที่มี privacy_n 1..MIN_CELL-1
    ใช้กับจำนวนเสียชีวิตจาก HOSxP (CKD/CVD) ซึ่งเลือกดูรายเดือนได้ — ย้อนหาได้ว่าใครเสียชีวิตด้วยโรคอะไร"""
    if not MIN_CELL:
        return data

    def walk(v):
        if isinstance(v, dict):
            n = v.get("privacy_n")
            out = {k: walk(x) for k, x in v.items() if k != "privacy_n"}
            if isinstance(n, int) and 0 < n < MIN_CELL:
                out["value"] = f"<{MIN_CELL}"
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v
    return walk(data)


class PrefixMiddleware:
    """รองรับการวางแอปไว้หลัง reverse proxy แบบ sub-path

    อ่าน X-Forwarded-Prefix มาตั้ง SCRIPT_NAME และ X-Forwarded-Proto มาตั้ง url_scheme
    ทำให้ url_for() สร้างลิงก์ /ncd/... ถูก และยังเข้าตรง :5400 บน LAN ได้เหมือนเดิม
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        # เชื่อ header จาก reverse proxy บนเครื่องเดียวกันเท่านั้น — เครื่องอื่นส่ง prefix ปลอมมาแก้ลิงก์ในหน้าไม่ได้
        trusted = environ.get("REMOTE_ADDR", "") in TRUSTED_PROXIES
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", "") if trusted else ""
        if prefix and (not prefix.startswith("/") or any(c in prefix for c in '"<>\'\\ ') or prefix.startswith("//")):
            prefix = ""
        if prefix:
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
            path = environ.get("PATH_INFO", "")
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix):] or "/"
        proto = environ.get("HTTP_X_FORWARDED_PROTO") if trusted else None
        if proto in ("http", "https"):
            environ["wsgi.url_scheme"] = proto
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = PrefixMiddleware(app.wsgi_app)
app.jinja_env.filters["n"] = ui.fmt_int
pages.load()
_nl = logging.getLogger("ncd")                  # บันทึกผลการดึง HDC/อุ่นแคชลง stderr → journal
if not _nl.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _nl.addHandler(_h)
_nl.setLevel(logging.INFO)
if os.getenv("NCD_WARM", "1") == "1":      # อุ่นแคชหน้าเริ่มต้นล่วงหน้า + รีเฟรชเป็นระยะ (ปิดด้วย NCD_WARM=0 · test/dev ปิดไว้)
    pages.start_hdc_syncer()
    pages.start_warmer()

_ICONS = {}


def icon(name):
    """ไอคอน Lucide แบบ inline SVG จาก static/icons (ไม่พึ่ง CDN) — ไม่พบไฟล์คืนข้อความว่าง"""
    if name not in _ICONS:
        path = os.path.join(HERE, "static", "icons", os.path.basename(str(name)) + ".svg")
        try:
            with open(path, encoding="utf-8") as f:
                svg = re.sub(r"<!--.*?-->", "", f.read(), flags=re.S).strip()
            _ICONS[name] = Markup(re.sub(r'\s+(width|height)="24"', "", svg, count=2)
                                  .replace('class="lucide', 'class="ic lucide', 1))
        except OSError:
            _ICONS[name] = Markup("")
    return _ICONS[name]


def qs(**over):
    """query string ปัจจุบัน + ค่าที่ override (None = ลบคีย์)"""
    args = {k: v for k, v in request.args.items() if k not in ("print",)}
    for k, v in over.items():
        if v is None:
            args.pop(k, None)
        else:
            args[k] = v
    return ("?" + urlencode(args)) if args else ""


def list_url(page_key, ind, g):
    """ลิงก์หน้ารายชื่อ — คงปีงบ/ช่วงข้อมูลที่กำลังดูอยู่"""
    args = {k: request.args[k] for k in ("fy", "scope", "grp") if k in request.args}
    args["g"] = g
    return url_for("patient_list", key=page_key, ind=ind) + "?" + urlencode(args)


def _on_lan():
    return check.request_allowed(request.remote_addr or "", request.headers)


app.jinja_env.globals.update(icon=icon, qs=qs, bar_geometry=ui.bar_geometry,
                             donut_segments=ui.donut_segments, fmt_pct=ui.fmt_pct, list_url=list_url)


def _today():
    return app.config.get("TODAY") or date.today()


@app.teardown_appcontext
def _close_db(_exc):
    """คืน connection ของ request นี้ (db.py ใช้ connection เดียวทุกคำสั่งใน request)"""
    db.close()


def _scope_options():
    opts = [("year", "ทั้งปีงบประมาณ"), ("q1", "ไตรมาส 1 (ต.ค.–ธ.ค.)"), ("q2", "ไตรมาส 2 (ม.ค.–มี.ค.)"),
            ("q3", "ไตรมาส 3 (เม.ย.–มิ.ย.)"), ("q4", "ไตรมาส 4 (ก.ค.–ก.ย.)")]
    for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        opts.append((f"m{m}", "เดือน " + periods.THAI_MONTHS[m - 1]))
    return opts


def _build(key):
    """(data, period, src) ของหน้า key — ส่วนที่ล้มกลายเป็นข้อความผิดพลาด ไม่ทำให้ทั้งหน้าล้ม"""
    if key not in pages.KEYS:
        abort(404)
    p = periods.parse(request.args, _today())
    src = request.args.get("src", "hosxp")
    if src not in ("hosxp", "hdc"):
        src = "hosxp"
    return pages.get(key, p, src, request.args.to_dict()), p, src


def _ctx(key, p, src, data):
    today = _today()
    cur = periods.fiscal_year(today)
    return dict(
        data=data, key=key, nav=pages.NAV, p=p, src=src, today=today,
        print_mode=request.args.get("print") == "1", version=VERSION,
        hospital=os.getenv("NCD_HOSPITAL_NAME", "โรงพยาบาลวังน้ำเขียว"),
        fy_options=list(range(cur, cur - 5, -1)), scope_options=_scope_options(),
        as_of=today.strftime("%d/%m/") + str(today.year + 543), audited=check.data_audited(),
        can_list=_on_lan() and not request.args.get("print") == "1")


@app.route("/", defaults={"key": "overview"})
@app.route("/<key>")
def page(key):
    data, p, src = _build(key)
    return render_template("page.html", **_ctx(key, p, src, data if _on_lan() else public_view(data)))


_check_lock = threading.Lock()


@app.route("/check")
def check_page():
    """Data Audit — เปิดเฉพาะ LAN (หลัง proxy ตรวจ X-Forwarded-For ด้วย)"""
    if not _on_lan() or not check.host_allowed(request.host):
        abort(403)
    p = periods.parse(request.args, _today())
    # ยิงฐาน ~67 คำสั่งต่อครั้ง — ให้ตรวจได้ทีละครั้ง คนที่ 2 ได้ "ไม่ว่าง" ทันที ไม่ซ้อนภาระบนฐาน HOSxP
    if not _check_lock.acquire(blocking=False):
        return ("กำลังตรวจข้อมูลของผู้ใช้อื่นอยู่ ลองใหม่ในอีกครู่", 503,
                {"Retry-After": "30", "Content-Type": "text/plain; charset=utf-8"})
    try:
        rows = check.audit(p)
    finally:
        _check_lock.release()
    return render_template("check.html", rows=rows, summary=check.summary(rows),
                           **_ctx("check", p, "hosxp", {"title": "ตรวจก่อนใช้ (Data Audit)"}))


@app.route("/list/<key>/<ind>")
def patient_list(key, ind):
    """รายชื่อผู้ป่วยจากตัวชี้วัด — เปิดเฉพาะเครือข่าย LAN ของ รพ. (จากอินเทอร์เน็ต/Cloudflare ได้ 403 โดยไม่แตะฐาน)"""
    p = periods.parse(request.args, _today())
    if not _on_lan() or not check.host_allowed(request.host):
        resp = make_response(render_template("list.html", denied=True,
                                             **_ctx(key, p, "hosxp", {"title": "ดูรายชื่อได้เฉพาะในเครือข่ายโรงพยาบาล"})), 403)
    else:
        if key not in LIST_PAGES:
            abort(404)
        g = request.args.get("g", "miss")
        try:
            lst = LIST_PAGES[key](p, ind, g)
        except KeyError:
            abort(404)
        except Exception as e:      # noqa: BLE001 — ฐานล่ม/ช้า: แจ้งในหน้า ไม่แสดง traceback
            logging.getLogger("ncd").exception("รายชื่อ %s/%s ล้ม", key, ind)
            lst = {"error": f"ดึงรายชื่อไม่ได้ ({type(e).__name__})", "title": "รายชื่อผู้ป่วย"}
        resp = make_response(render_template("list.html", denied=False, lst=lst,
                                             **_ctx(key, p, "hosxp", {"title": lst["title"]})))
    resp.headers["Cache-Control"] = "no-store"          # ห้ามเบราว์เซอร์/พร็อกซีเก็บหน้าที่มีชื่อผู้ป่วย
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@app.route("/api/<key>.json")
def api(key):
    data, _p, _src = _build(key)
    return jsonify(data if _on_lan() else public_view(data))


@app.route("/healthz")
def healthz():
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host=os.getenv("NCD_HOST", "127.0.0.1"), port=int(os.getenv("NCD_PORT", "5400")),
            debug=os.getenv("FLASK_DEBUG") == "1")
