"""Tien ich chung cho test core."""
import hashlib
import os

from core.chunker import ChunkerParams
from core.repo_local import LocalRepo
from core.repository import Repository, init_repo
from shared.snapshot import long_path

FAST_SCRYPT = {"n": 2 ** 12}       # test chay nhanh; mac dinh that la 2^15
PASSWORD = "mật-khẩu-thử 123"
SMALL = ChunkerParams(2 * 1024, 8 * 1024, 64 * 1024)


def new_repo(path, params=ChunkerParams(), pack_target=16 * 1024 * 1024, password=PASSWORD):
    return init_repo(LocalRepo(path), password, params, pack_target, scrypt=FAST_SCRYPT)


def reopen(path, password=PASSWORD):
    return Repository.open(LocalRepo(path), password)


def write(path, data):
    p = long_path(str(path))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def file_hashes(root):
    """{duong dan tuong doi '/': sha256} cua moi file (ho tro duong dan dai)."""
    out = {}
    base = long_path(str(root))
    for dp, _, files in os.walk(base):
        for f in files:
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, base).replace("\\", "/")] = hashlib.sha256(fh.read()).hexdigest()
    return out


def dirs_of(root):
    base = long_path(str(root))
    return {os.path.relpath(os.path.join(dp, d), base).replace("\\", "/")
            for dp, ds, _ in os.walk(base) for d in ds}
