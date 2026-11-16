from flask import Flask, url_for

import db
from app import PrefixMiddleware, app


def test_healthz():
    r = app.test_client().get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_prefix_middleware_sets_script_name():
    probe = Flask(__name__)

    @probe.route("/p")
    def p():
        return url_for("static", filename="x.css")

    probe.wsgi_app = PrefixMiddleware(probe.wsgi_app)
    r = probe.test_client().get("/ncd/p", headers={"X-Forwarded-Prefix": "/ncd"})
    assert r.get_data(as_text=True) == "/ncd/static/x.css"


def test_healthz_under_prefix():
    r = app.test_client().get("/ncd/healthz", headers={"X-Forwarded-Prefix": "/ncd"})
    assert r.status_code == 200


def test_bind_escapes_percent():
    sql = db._bind("select '100%%', %(a)s", {"a": 1})
    assert "100%" in sql and "%%" not in sql and sql.rstrip().endswith("1")
