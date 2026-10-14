"""2c crypto: key file (scrypt), chunk ID HMAC, ma hoa mau AES-GCM."""
import json
import os

import pytest

from core.crypto import Keys, key_id, make_key_file, open_key_file
from core.errors import IntegrityError, RepoError, WrongPassword
from tests.core_helpers import FAST_SCRYPT


def test_key_file_khu_hoi_va_sai_mat_khau():
    k = Keys.generate("r1")
    kf = make_key_file(k, "đúng", scrypt=FAST_SCRYPT)
    doc = json.loads(kf)
    assert doc["kdf"]["name"] == "scrypt" and doc["wrap"]["cipher"] == "AES-256-GCM"
    assert b"enc_key" not in kf                         # khoa chu khong o dang ro
    k2 = open_key_file(kf, "đúng")
    assert (k2.enc_key, k2.id_key, k2.repo_id) == (k.enc_key, k.id_key, "r1")
    with pytest.raises(WrongPassword):
        open_key_file(kf, "sai")
    with pytest.raises(RepoError):
        open_key_file(b"{khong phai json", "đúng")
    assert key_id(kf) == key_id(kf) and len(key_id(kf)) == 64


def test_chunk_id_co_khoa():
    a, b = Keys.generate("r"), Keys.generate("r")
    assert a.chunk_id(b"x") == a.chunk_id(b"x")
    assert a.chunk_id(b"x") != b.chunk_id(b"x")         # khoa khac -> ID khac (khong doan duoc noi dung)


def test_ma_hoa_mau_khu_hoi_nen_va_xac_thuc():
    k = Keys.generate("r")
    text = b"du lieu lap lai " * 4000
    rnd = os.urandom(50_000)
    for data in (b"", b"a", text, rnd):
        cid = k.chunk_id(data)
        blob = k.encrypt_chunk(cid, data)
        assert k.decrypt_chunk(cid, blob, len(data)) == data
    assert len(k.encrypt_chunk(k.chunk_id(text), text)) < len(text) // 10        # da nen zstd
    assert len(k.encrypt_chunk(k.chunk_id(rnd), rnd)) == len(rnd) + 1 + 12 + 16  # kho nen -> giu nguyen

    cid = k.chunk_id(text)
    blob = bytearray(k.encrypt_chunk(cid, text))
    blob[20] ^= 1
    with pytest.raises(IntegrityError):
        k.decrypt_chunk(cid, bytes(blob))
    good = k.encrypt_chunk(cid, text)
    with pytest.raises(IntegrityError):                 # trao blob sang ID khac -> AAD sai
        k.decrypt_chunk(k.chunk_id(b"khac"), good)
    with pytest.raises(IntegrityError):                 # sai khoa
        Keys.generate("r").decrypt_chunk(cid, good)
