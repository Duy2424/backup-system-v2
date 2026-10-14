"""Fixture dung chung: server that (werkzeug) chay trong thread voi thu muc tam rieng."""
import threading

import pytest
from werkzeug.serving import make_server

from shared import config, database


@pytest.fixture()
def env(tmp_path, monkeypatch):
    work = tmp_path / "work"
    for name, path in {
        "WORK_DIR": work, "BACKUP_TEMP_DIR": work / "backup_temp", "RESTORE_TEMP_DIR": work / "restore_temp",
        "SNAPSHOTS_DIR": work / "snapshots", "LOGS_DIR": work / "logs", "SQL_BACKUP_TEMP": work / "sql",
        "INSTANCE_DIR": tmp_path / "instance", "STORAGE_DIR": tmp_path / "storage",
        "DB_PATH": tmp_path / "test.db",
    }.items():
        monkeypatch.setattr(config, name, str(path))
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin-pass-123")

    # Khong goi PowerShell trong test (cham + phu thuoc may)
    from agent import system_state
    monkeypatch.setattr(system_state, "capture_system_state",
                        lambda comps=None: {"platform": "test", "hostname": "test", "components": list(comps or [])})

    from server.server import create_app
    app = create_app()
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    monkeypatch.setattr(config, "SERVER_URL", f"http://127.0.0.1:{srv.port}")

    class Env:
        pass
    e = Env()
    e.app, e.tmp, e.url = app, tmp_path, config.SERVER_URL
    e.admin = database.get_user_by_username("admin")
    yield e
    srv.shutdown()
