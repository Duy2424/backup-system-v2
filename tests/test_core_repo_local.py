"""2e repo_local: kho thu muc - chi cho them, ghi nguyen tu, index dung lai duoc."""
import hashlib
import os

import pytest

from core import packer
from core.crypto import Keys
from core.errors import IntegrityError, NotFound, RepoError
from core.repo_local import LocalRepo


def make_pack(keys, payloads):
    w = packer.PackWriter(keys)
    for p in payloads:
        cid = keys.chunk_id(p)
        w.add(cid, keys.encrypt_chunk(cid, p), len(p))
    return w.finish()


def test_pack_missing_locate_va_index_dung_lai(tmp_path):
    k = Keys.generate("r")
    repo = LocalRepo(tmp_path)
    pid, data, entries = make_pack(k, [b"a" * 100, b"b" * 200])
    ids = [e.id.hex() for e in entries]
    other = "f" * 64
    assert repo.missing_chunks(ids + [other, other]) == ids + [other]
    assert repo.put_pack(pid, data) == "created"
    assert repo.put_pack(pid, data) == "exists"                     # idempotent, khong ghi de
    assert repo.missing_chunks(ids + [other]) == [other]
    assert repo.locate_chunks(ids + [other]) == {ids[0]: pid, ids[1]: pid}
    assert repo.get_pack(pid) == data and repo.get_pack(pid, 0, 8) == packer.HEADER
    # mo lai (tien trinh moi): index dung lai tu footer + bang ID
    assert LocalRepo(tmp_path).missing_chunks(ids) == []
    assert not list((tmp_path / "tmp").iterdir())                    # khong de lai file tam


def test_tu_choi_du_lieu_sai(tmp_path):
    k = Keys.generate("r")
    repo = LocalRepo(tmp_path)
    pid, data, _ = make_pack(k, [b"x" * 50])
    with pytest.raises(IntegrityError):
        repo.put_pack("0" * 64, data)                                # sai SHA
    with pytest.raises(IntegrityError):
        bad = b"rac" * 30
        repo.put_pack(hashlib.sha256(bad).hexdigest(), bad)          # SHA dung nhung sai cau truc
    with pytest.raises(RepoError):
        repo.put_pack("../../x", data)
    with pytest.raises(NotFound):
        repo.get_pack("a" * 64)
    with pytest.raises(IntegrityError):
        repo.put_snapshot(hashlib.sha256(b"x").hexdigest(), b"x")


def test_config_va_key_ghi_mot_lan(tmp_path):
    repo = LocalRepo(tmp_path)
    assert repo.put_config(b"{}") == "created"
    assert repo.put_config(b"{}") == "exists"
    with pytest.raises(RepoError):
        repo.put_config(b'{"khac": 1}')
    kf = b"key file"
    assert repo.put_key(hashlib.sha256(kf).hexdigest(), kf) == "created"
    with pytest.raises(IntegrityError):
        repo.put_key("1" * 64, kf)


def test_khong_co_lenh_xoa():
    assert not [m for m in dir(LocalRepo) if "delete" in m or "remove" in m or "prune" in m]
