"""
Tuan 5 (A): giu ban sao luu theo chinh sach + don du lieu khong con dung.

CHAY CUC BO tren PC giu kho, bang tai khoan quan tri, trong khung gio bao tri (dung dich vu API kho
truoc - viec cua Nguoi B). API kho van KHONG co lenh xoa (docs/repo-format.md muc 13).

Chinh sach mac dinh: giu 24 ban theo gio / 7 theo ngay / 4 theo tuan / 3 theo thang (kieu restic:
moi "khung" giu ban MOI NHAT; ban moi nhat cua moi nhom may+thu muc luon duoc giu; snapshot khong
giai ma duoc thi KHONG xoa).

Thu tu an toan khi --apply:
  1. pack chi con mot phan duoc dung -> chep cac blob con dung (giu nguyen ban ma hoa) sang pack moi
  2. xoa snapshot het han
  3. xoa pack khong con dung + pack da chep lai
  4. dung lai index, kiem tra MOI mau cua snapshot duoc giu van con -> neu thieu: bao loi to
Sap giua chung: chi de lai pack mo coi (lan don sau xu ly), khong mat du lieu cua ban duoc giu.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime

from core import packer
from core.errors import IntegrityError, RepoError
from core.repo_local import LocalRepo

POLICY_DEFAULT = {"hourly": 24, "daily": 7, "weekly": 4, "monthly": 3}
_BUCKET = {
    "hourly": lambda t: t.strftime("%Y-%m-%d %H"),
    "daily": lambda t: t.strftime("%Y-%m-%d"),
    "weekly": lambda t: "%d-W%02d" % t.isocalendar()[:2],
    "monthly": lambda t: t.strftime("%Y-%m"),
}


class AdminLocalRepo(LocalRepo):
    """LocalRepo + quyen xoa. CHI dung trong cong cu don chay cuc bo, khong bao gio qua API."""

    def _rm(self, p):
        try:
            os.chmod(p, 0o600)
            os.remove(p)
        except FileNotFoundError:
            pass

    def delete_snapshot(self, sid):
        self._rm(self.root / "snapshots" / sid)

    def delete_pack(self, pid):
        self._rm(self._pack_path(pid))
        self._index = None


def select_keep(snaps, policy=None):
    """snaps: list tu Repository.list_snapshots(). Tra ve (keep: {id: [ly do]}, forget: [id])."""
    policy = POLICY_DEFAULT if policy is None else policy
    keep, groups = {}, {}
    for s in snaps:
        if "error" in s:
            keep.setdefault(s["id"], []).append("không giải mã được - không xoá")
            continue
        groups.setdefault((s["host"], tuple(s["sources"])), []).append(s)
    for items in groups.values():
        items.sort(key=lambda s: s["time"], reverse=True)
        keep.setdefault(items[0]["id"], []).append("mới nhất")
        for rule, n in policy.items():
            if not n:
                continue
            seen = []
            for s in items:
                b = _BUCKET[rule](datetime.fromisoformat(s["time"]))
                if b in seen:
                    continue
                seen.append(b)
                keep.setdefault(s["id"], []).append(f"{rule} {b}")
                if len(seen) >= n:
                    break
    forget = [s["id"] for s in snaps if s["id"] not in keep]
    return keep, forget


@dataclass
class PrunePlan:
    keep: dict
    forget: list
    delete_packs: list = field(default_factory=list)       # khong con mau nao duoc dung
    repack: dict = field(default_factory=dict)              # pack -> [chunk id con dung]
    bytes_free: int = 0
    bytes_repack: int = 0


def plan_prune(repo, policy=None, repack_threshold=0.3):
    if not isinstance(repo.backend, LocalRepo):
        raise RepoError("Dọn kho chỉ chạy cục bộ trên máy giữ kho (--repo là thư mục), không qua API")
    snaps = repo.list_snapshots()
    keep, forget = select_keep(snaps, policy)
    used = set()
    for sid in keep:
        try:
            used.update(h for e in repo.load_snapshot(sid)["tree"] for h in e.get("chunks", ()))
        except (IntegrityError, RepoError, ValueError):
            pass
    plan = PrunePlan(keep, forget)
    be = repo.backend
    for pid in be.list_packs():
        path = be._pack_path(pid)
        ids = be._ids_of_pack(path)
        live = [i for i in ids if i in used]
        size = path.stat().st_size
        if not live:
            plan.delete_packs.append(pid)
            plan.bytes_free += size
        elif 1 - len(live) / len(ids) >= repack_threshold:
            plan.repack[pid] = live
            plan.bytes_repack += size
    return plan


def run_prune(repo, plan, log=print):
    """Thuc hien plan (sau khi da xem chay thu). Tra ve so byte da giai phong."""
    be = repo.backend
    if not isinstance(be, AdminLocalRepo):
        be = AdminLocalRepo(be.root)
        repo.backend = be
    lock = be.root / "locks" / "prune.lock"
    lock.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RepoError(f"Đang có tiến trình dọn kho khác ({lock}) - nếu chắc chắn không có, xoá file này") from None
    os.close(fd)
    before = sum(be._pack_path(p).stat().st_size for p in be.list_packs())
    try:
        # 1. chep blob con dung sang pack moi (khong giai ma: blob giu nguyen, index ma hoa lai)
        for pid, live in plan.repack.items():
            data = be.get_pack(pid)
            entries = {e.id.hex(): e for e in packer.verify_pack(data, pid, repo.keys, read_data=False)}
            w = packer.PackWriter(repo.keys, repo.pack_target)
            for h in live:
                e = entries[h]
                if w.would_overflow(e.length):
                    new_id, new_data, _ = w.finish()
                    be.put_pack(new_id, new_data)
                    w = packer.PackWriter(repo.keys, repo.pack_target)
                w.add(e.id, packer.blob_of(data, e), e.raw_length)
            new_id, new_data, _ = w.finish()
            be.put_pack(new_id, new_data)
            log(f"Chép lại pack {pid[:12]}: giữ {len(live)} mẩu -> {new_id[:12]}")
        # 2. snapshot het han
        for sid in plan.forget:
            be.delete_snapshot(sid)
            log(f"Xoá snapshot {sid[:12]}")
        # 3. pack khong con dung + pack da chep lai
        for pid in plan.delete_packs + list(plan.repack):
            be.delete_pack(pid)
        log(f"Xoá {len(plan.delete_packs) + len(plan.repack)} pack")
        # 4. kiem tra lai
        be._index = None
        rep = repo.check(read_data=False)
        if rep["errors"]:
            raise IntegrityError("SAU KHI DỌN KHO CÓ LỖI - dừng mọi thao tác, kiểm tra ngay: " + "; ".join(rep["errors"][:5]))
    finally:
        os.remove(lock)
    after = sum(be._pack_path(p).stat().st_size for p in be.list_packs())
    return before - after
