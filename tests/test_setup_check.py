import db
import setup_check


def test_risky_privs_detects_write_rights():
    grants = ["GRANT SELECT ON `hos`.* TO `ncd`@`%`", "GRANT INSERT, UPDATE ON `hos`.* TO `ncd`@`%`"]
    assert setup_check.risky_privs(grants, "hos") == ["INSERT", "UPDATE"]


def test_risky_privs_ignores_other_databases_and_select_only():
    assert setup_check.risky_privs(["GRANT ALL PRIVILEGES ON `test`.* TO `u`@`%`"], "hos") == []
    assert setup_check.risky_privs(["GRANT SELECT, USAGE ON *.* TO `u`@`%`"], "hos") == []
    assert setup_check.risky_privs(["GRANT SELECT (a, b) ON `hos`.`t` TO `u`@`%`"], "hos") == []


def test_risky_privs_global_all_and_grant_option():
    out = setup_check.risky_privs(["GRANT ALL PRIVILEGES ON *.* TO `u`@`%` WITH GRANT OPTION"], "hos")
    assert "ALL PRIVILEGES" in out and "GRANT OPTION" in out


def test_main_fails_with_exit_1_when_db_unreachable(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("cannot connect")

    monkeypatch.setattr(db, "fetch", boom)
    monkeypatch.setattr(db, "fetch_one", boom)
    assert setup_check.main(["--no-audit"]) == 1
    assert "✘" in capsys.readouterr().out


def test_main_ok_with_read_only_grants(fake_db, monkeypatch, capsys):
    fake_db.add("show grants", [{"Grants for ncd@%": "GRANT SELECT ON `hos`.* TO `ncd`@`%`"}])
    fake_db.add("regexp", [{"name": "โรคเบาหวาน"}])
    fake_db.add("max(vstdate)", [{"d": __import__("datetime").date.today()}])
    assert setup_check.main(["--no-audit"]) == 0
    out = capsys.readouterr().out
    assert "  ✔ " in out and "  ✘ " not in out          # สรุปท้ายรายงานมีสัญลักษณ์ ✘ เสมอ จึงเช็คเฉพาะบรรทัดผลตรวจ


def test_main_fails_when_account_can_write(fake_db, capsys):
    fake_db.add("show grants", [{"Grants for ncd@%": "GRANT ALL PRIVILEGES ON `hos`.* TO `ncd`@`%`"}])
    fake_db.add("regexp", [{"name": "โรคเบาหวาน"}])
    assert setup_check.main(["--no-audit"]) == 1
    assert "ALL PRIVILEGES" in capsys.readouterr().out


def test_main_fails_when_thai_text_is_garbled(fake_db, capsys):
    fake_db.add("show grants", [{"Grants for ncd@%": "GRANT SELECT ON `hos`.* TO `ncd`@`%`"}])
    fake_db.add("regexp", [])                                        # ไม่พบชื่อที่เป็นภาษาไทยอ่านได้
    assert setup_check.main(["--no-audit"]) == 1


def test_missing_table_is_failure(fake_db, monkeypatch, capsys):
    fake_db.add("show grants", [{"Grants for ncd@%": "GRANT SELECT ON `hos`.* TO `ncd`@`%`"}])
    fake_db.add("regexp", [{"name": "โรคเบาหวาน"}])
    fake_db.add("from lab_order ", RuntimeError("Table 'hos.lab_order' doesn't exist"))
    assert setup_check.main(["--no-audit"]) == 1
    assert "lab_order" in capsys.readouterr().out


def test_audit_errors_become_failures(fake_db, monkeypatch, capsys):
    import check
    fake_db.add("show grants", [{"Grants for ncd@%": "GRANT SELECT ON `hos`.* TO `ncd`@`%`"}])
    fake_db.add("regexp", [{"name": "โรคเบาหวาน"}])
    monkeypatch.setattr(check, "audit", lambda p: [
        {"item": "คลินิก HT", "app_uses": "002", "found": "ไม่พบ", "status": "error", "env_hint": "NCD_CLINIC_HT"},
        {"item": "lab LDL", "app_uses": "270", "found": "0 ราย", "status": "warn", "env_hint": "NCD_LAB_LDL"}])
    assert setup_check.main([]) == 1
    out = capsys.readouterr().out
    assert "NCD_CLINIC_HT" in out and "⚠" in out
