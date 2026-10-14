"""
Agent - chay tren may can backup (trong do an: PC o nha, cung may voi server).

  - Poll server moi AGENT_POLL_INTERVAL giay lay job CUA chinh user so huu token.
  - Moi lan poll gui kem ten may/phien ban -> web hien agent online/offline.
  - Bao tien do toi da ~2 lan/giay; server tra ve co 'cancel' khi nguoi dung bam Huy.
  - Lan poll dau tien (startup=1): server danh dau cac job 'running' cu la that bai.

Chay:  python -m agent.agent      (hoac agent\\start_agent.bat)
"""
import logging
import os
import platform
import sys
import time
import traceback

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from shared import config  # noqa: E402
from shared.log import setup_logging  # noqa: E402
from shared.text import vn_int, vn_mb, vn_num  # noqa: E402
from agent import backup_logic, folder_browser, restore_logic  # noqa: E402
from agent.backup_logic import JobCancelled  # noqa: E402

log = logging.getLogger("agent")


class ServerApi:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "X-Auth-Token": token,
            "X-Agent-Host": platform.node(),
            "X-Agent-Version": config.VERSION,
            "X-Agent-Platform": platform.platform(),
            "X-Agent-Browser-Port": str(config.BROWSER_PORT),
        })

    def poll(self, startup=False):
        r = self.s.get(f"{self.url}/api/jobs/poll", params={"startup": int(startup)}, timeout=15)
        if r.status_code == 401:
            raise PermissionError("AGENT_TOKEN không hợp lệ")
        r.raise_for_status()
        return r.json().get("job")

    def update(self, job_id, **data):
        try:
            r = self.s.post(f"{self.url}/api/jobs/{job_id}/update", json=data, timeout=10)
            return r.json() if r.ok else {}
        except requests.RequestException as e:
            log.warning("Không gửi được tiến độ job #%s: %s", job_id, e)
            return {}

    def backup_done(self, job_id, payload):
        r = self.s.post(f"{self.url}/api/jobs/{job_id}/backup_done", json=payload, timeout=30)
        r.raise_for_status()


class Reporter:
    """Gui tien do co gioi han tan suat; nem JobCancelled neu server bao huy."""

    def __init__(self, api, job_id, min_interval=0.5):
        self.api, self.job_id, self.min_interval = api, job_id, min_interval
        self.last_t, self.last_p = 0.0, -1

    def __call__(self, pct, msg, force=False):
        now = time.monotonic()
        if not force and pct < 100 and now - self.last_t < self.min_interval and pct - self.last_p < 5:
            return
        self.last_t, self.last_p = now, pct
        resp = self.api.update(self.job_id, progress=min(int(pct), 100), message=msg)
        if resp.get("cancel"):
            raise JobCancelled()


def handle_backup(api, job):
    user, params = job["_user"], job.get("params") or {}
    rep = Reporter(api, job["id"])
    result = backup_logic.perform_backup(user, paths=params.get("paths"),
                                         components=params.get("components"), progress_cb=rep)
    api.backup_done(job["id"], {
        "filename": result["filename"], "size": result["size"], "sha256": result["sha256"],
        "snapshot_summary": result["snapshot_summary"], "stats": result["stats"],
        "paths": params.get("paths") or config.DEFAULT_BACKUP_PATHS, "components": result["components"],
    })
    s = result["stats"]
    return (f"Sao lưu xong: {vn_int(s['files'])} file, gửi {vn_mb(s['bytes_uploaded'])}, "
            f"{vn_num(s['seconds'])} giây" + (f", bỏ qua {s['skipped']} file" if s["skipped"] else ""))


def handle_restore(api, job):
    user, params = job["_user"], job.get("params") or {}
    if not params.get("filename"):
        raise ValueError("Job khôi phục thiếu tên file")
    rep = Reporter(api, job["id"])

    def progress(p, m):
        rep(p, m)
        if p >= 100 and not params.get("dry_run"):
            # Bao xong TRUOC khi doi IP/firewall (co the cat ket noi toi server)
            api.update(job["id"], status="completed", progress=100, message=m, completed=True)

    res = restore_logic.perform_restore(
        user, params["filename"], progress_cb=progress, dry_run=bool(params.get("dry_run")),
        delete_extra=bool(params.get("delete_extra")), target_dir=params.get("target_dir") or None,
        restore_system=params.get("restore_system", True))
    s = res["compare_result"]["summary"]
    head = "Chạy thử" if res["dry_run"] else "Khôi phục xong"
    msg = (f"{head}: thêm {s['to_add']}, ghi đè {s['to_overwrite']}, "
           f"{'xoá' if params.get('delete_extra') else 'thừa (giữ lại)'} {s['to_delete']}, "
           f"giữ nguyên {s['unchanged']}")
    if res["system_diffs"]:
        msg += f"; cấu hình hệ thống khác {len(res['system_diffs'])} mục"
    return msg


def run_job(api, job):
    jid, jtype = job["id"], job.get("job_type")
    log.info("Nhận job #%s (%s)", jid, jtype)
    try:
        msg = (handle_backup if jtype == "backup" else handle_restore)(api, job) \
            if jtype in ("backup", "restore") else None
        if msg is None:
            raise ValueError(f"Loại job không hỗ trợ: {jtype}")
        api.update(jid, status="completed", progress=100, message=msg, completed=True)
        log.info("Job #%s xong: %s", jid, msg)
    except JobCancelled:
        api.update(jid, status="cancelled", message="Đã huỷ theo yêu cầu", completed=True)
        log.info("Job #%s đã huỷ", jid)
    except Exception as e:      # noqa: BLE001 - moi loi deu bao ve server
        log.error("Job #%s lỗi: %s\n%s", jid, e, traceback.format_exc())
        api.update(jid, status="failed", message=f"Lỗi: {e}", completed=True)


def main_loop():
    if not config.AGENT_TOKEN:
        log.error("Chưa có AGENT_TOKEN. Lấy token ở trang Cài đặt trên web rồi điền vào agent/agent_config.txt")
        sys.exit(2)
    api = ServerApi(config.SERVER_URL, config.AGENT_TOKEN)
    startup, backoff = True, config.AGENT_POLL_INTERVAL
    log.info("Kết nối server %s (poll %ss)", config.SERVER_URL, config.AGENT_POLL_INTERVAL)
    while True:
        try:
            job = api.poll(startup=startup)
            if startup:
                log.info("Đã kết nối server")
            startup, backoff = False, config.AGENT_POLL_INTERVAL
            if job:
                run_job(api, job)
                continue
        except PermissionError as e:
            log.error("%s - sửa agent_config.txt", e)
            backoff = 30
        except requests.RequestException as e:
            log.warning("Mất kết nối server: %s", e)
            backoff = min(backoff * 2, 60)
        time.sleep(backoff)


def main():
    config.ensure_dirs()
    setup_logging("agent", config.LOGS_DIR)
    log.info("BACKUP AGENT %s - máy %s", config.VERSION, platform.node())
    folder_browser.start_browser_server()
    try:
        main_loop()
    except KeyboardInterrupt:
        log.info("Dừng agent")


if __name__ == "__main__":
    main()
