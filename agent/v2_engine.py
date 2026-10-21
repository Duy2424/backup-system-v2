"""
Agent chay job web bang loi v2 (core/). Bat bang ENGINE=v2 trong agent_config.txt.

- Sao luu: thu muc nguoi dung chon + (neu chon thanh phan mang/he thong) file v2_he_thong/system_state.json
  ghi nhan luc sao luu -> ca hai nam trong CUNG snapshot.
- Ten ban sao luu bao ve server: "v2-<snapshot_id>". Server chi luu thong ke, khong giu khoa/du lieu giai ma.
- Khoi phuc: ra thu muc khac, hoac VE VI TRI CU (bo qua file khong doi, xoa file thua chi khi bat);
  ap lai cau hinh mang tu system_state.json trong snapshot khi duoc yeu cau.
"""
import json
import logging
import os
import shutil
import tempfile

from core.repo_http import HttpRepo
from core.repo_local import LocalRepo
from core.repository import Repository
from shared import config

log = logging.getLogger("agent.v2")
PREFIX = "v2-"
STATE_ROOT = "v2_he_thong"


def is_v2_name(name):
    return isinstance(name, str) and name.startswith(PREFIX) and len(name) == len(PREFIX) + 64


class V2Engine:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self._repo = None

    def repo(self):
        if self._repo is None:
            c = self.cfg
            if not c.V2_REPO or not c.V2_PASSWORD_FILE:
                raise RuntimeError("ENGINE=v2 nhưng thiếu V2_REPO / V2_PASSWORD_FILE trong agent_config.txt")
            with open(c.V2_PASSWORD_FILE, encoding="utf-8-sig") as f:
                password = f.readline().rstrip("\r\n")
            if c.V2_REPO.startswith(("http://", "https://")):
                limiter = None
                if c.V2_LIMIT_SCHEDULE:
                    from core.ratelimit import RateLimiter, Schedule
                    limiter = RateLimiter(Schedule.load(c.V2_LIMIT_SCHEDULE))
                backend = HttpRepo(c.V2_REPO, cert=c.V2_CERT or None, key=c.V2_KEY or None, ca=c.V2_CA or None,
                                   limiter=limiter)
            else:
                backend = LocalRepo(c.V2_REPO)
            self._repo = Repository.open(backend, password)
        return self._repo

    def _state_dir(self):
        d = os.path.join(self.cfg.WORK_DIR, STATE_ROOT)
        os.makedirs(d, exist_ok=True)
        return d

    def backup(self, paths, components, progress_cb=None, capture_state=None):
        """Tra ve payload backup_done cho server."""
        from agent import system_state
        comps = list(components or config.BACKUP_COMPONENTS)
        sources = [p for p in (paths or config.DEFAULT_BACKUP_PATHS) if os.path.exists(p)] if "files" in comps else []
        net = [c for c in comps if c != "files"]
        if net:
            state = (capture_state or system_state.capture_system_state)(net)
            with open(os.path.join(self._state_dir(), "system_state.json"), "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            sources.append(self._state_dir())
        if not sources:
            raise ValueError("Không có thư mục nào tồn tại để sao lưu")

        def progress(done, total, msg):
            if progress_cb:
                progress_cb(5 + int(90 * done / total) if total else 50, f"v2: {done / 1048576:,.0f}/{total / 1048576:,.0f} MB")

        res = self.repo().backup(sources, progress=progress)
        s = res["stats"]
        return {
            "engine": "v2", "filename": PREFIX + res["snapshot_id"], "snapshot_id": res["snapshot_id"],
            "size": s["bytes_uploaded"], "components": comps, "paths": [p for p in sources if p != self._state_dir()],
            "snapshot_summary": {"total_files": s["files"], "total_size": s["bytes"], "components": comps},
            "stats": {**s, "skipped": len(res["errors"])},
        }

    def restore(self, name, params, progress_cb=None):
        from agent import system_state
        sid = name[len(PREFIX):]
        repo = self.repo()

        def progress(done, total, msg):
            if progress_cb:
                progress_cb(5 + int(90 * done / total) if total else 50, f"v2: {done / 1048576:,.0f}/{total / 1048576:,.0f} MB")

        dry = bool(params.get("dry_run"))
        if params.get("target_dir"):
            st = repo.restore(sid, params["target_dir"], progress=progress) if not dry else {"to_write": 0}
        else:
            st = repo.restore(sid, in_place=True, delete_extra=bool(params.get("delete_extra")), dry_run=dry,
                              progress=progress)
        applied = False
        if params.get("restore_system", True) and not params.get("target_dir") and not dry:
            snap = repo.load_snapshot(sid)
            if any(e["path"] == f"{STATE_ROOT}/system_state.json" for e in snap["tree"]):
                tmp = tempfile.mkdtemp(prefix="bks-state-")
                try:
                    repo.restore(sid, tmp, include=f"{STATE_ROOT}/system_state.json")
                    with open(os.path.join(tmp, STATE_ROOT, "system_state.json"), encoding="utf-8") as f:
                        state = json.load(f)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
                if progress_cb:
                    progress_cb(100, "Khôi phục dữ liệu xong, đang áp dụng cấu hình hệ thống...")
                system_state.restore_system_state(state)
                applied = True
        return {"to_add_or_overwrite": st.get("to_write", 0), "unchanged": st.get("unchanged", 0),
                "deleted": st.get("deleted", 0), "system_applied": applied, "dry_run": dry}
