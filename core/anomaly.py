"""
Cong chan bat thuong truoc khi gui (tuan 6, A + B): phat hien som dau hieu ransomware.

Chay SAU khi quet + so voi snapshot cha, TRUOC khi doc/gui du lieu. Cac tin hieu:
  - file moi (canary): file ten "~bks_canary*" (hoac --canary) - nguoi dung khong bao gio sua;
    bi sua/xoa => bao dong ngay.
  - ti le thay doi: so file doi + them + mat / tong so file cua snapshot cha.
  - do ngau nhien: doc 64 KiB dau cua file da doi; file loai "van ban" (txt, csv, docx->xml...) ma
    entropy > 7,5 bit/byte la dau hieu bi ma hoa. Loai von da nen (jpg, zip, mp4...) khong tinh.
  - duoi file la (.locked, .encrypted, .crypt...).
Bao dong khi: file moi bi dong, HOAC (ti le thay doi >= max_change_ratio VA ti le file dang ngo
trong so file doi >= max_suspicious_ratio). Nguong chinh trong thresholds.
"""
import fnmatch
import math
import os
from collections import Counter

from core.errors import CoreError
from shared.snapshot import long_path

CANARY_PATTERNS = ["~bks_canary*"]
COMPRESSED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".zip", ".7z", ".rar", ".gz", ".mp4", ".mkv",
                  ".mp3", ".pdf", ".docx", ".xlsx", ".pptx", ".bak", ".trn", ".bkup", ".msi", ".exe", ".dll", ".cab"}
RANSOM_EXT = {".locked", ".encrypted", ".crypt", ".crypted", ".enc", ".lock", ".locky", ".wncry", ".ryk"}
DEFAULT = {"max_change_ratio": 0.30, "max_suspicious_ratio": 0.50, "entropy": 7.5, "sample": 65536, "min_files": 20}


class AnomalyDetected(CoreError):
    def __init__(self, report):
        super().__init__("Phát hiện bất thường, dừng sao lưu: " + "; ".join(report["reasons"]))
        self.report = report


def entropy(data):
    if not data:
        return 0.0
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in Counter(data).values())


def _is_canary(path, patterns):
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, p.lower()) for p in patterns)


def assess(entries, parent_snap, cache, thresholds=None, canaries=None):
    """entries: Entry tu scanner; cache: FileCache cua snapshot cha. Tra ve bao cao (dict)."""
    t = dict(DEFAULT, **(thresholds or {}))
    pats = list(CANARY_PATTERNS) + list(canaries or [])
    files = [e for e in entries if e.type == "file"]
    prev = {e["path"]: e for e in (parent_snap or {}).get("tree", []) if e.get("type") == "file"}
    current = {e.path for e in files}
    changed = [e for e in files if e.path in prev and cache.match(e) is None]
    added = [e for e in files if e.path not in prev]
    removed = [p for p in prev if p not in current]
    reasons = []

    canary_hit = [e.path for e in changed if _is_canary(e.path, pats)] + [p for p in removed if _is_canary(p, pats)]
    if canary_hit:
        reasons.append(f"file mồi bị sửa/xoá: {', '.join(canary_hit[:5])}")

    suspicious, sampled = [], 0
    for e in changed + added:
        ext = os.path.splitext(e.path)[1].lower()
        if ext in RANSOM_EXT:
            suspicious.append(e.path)
            continue
        if ext in COMPRESSED_EXT or e.size == 0:
            continue
        try:
            with open(long_path(e.abs), "rb") as f:
                data = f.read(t["sample"])
        except OSError:
            continue
        sampled += 1
        if entropy(data) > t["entropy"]:
            suspicious.append(e.path)

    base = max(len(prev), 1)
    change_ratio = (len(changed) + len(added) + len(removed)) / base
    touched = len(changed) + len(added)
    susp_ratio = len(suspicious) / touched if touched else 0.0
    if prev and len(prev) >= t["min_files"] and change_ratio >= t["max_change_ratio"] \
            and susp_ratio >= t["max_suspicious_ratio"]:
        reasons.append(f"{change_ratio:.0%} file thay đổi và {susp_ratio:.0%} trong số đó có dấu hiệu bị mã hoá")
    return {"alarm": bool(reasons), "reasons": reasons, "files": len(files), "changed": len(changed),
            "added": len(added), "removed": len(removed), "change_ratio": round(change_ratio, 4),
            "suspicious": len(suspicious), "suspicious_ratio": round(susp_ratio, 4), "sampled": sampled,
            "examples": suspicious[:10], "canary_hits": canary_hit}
