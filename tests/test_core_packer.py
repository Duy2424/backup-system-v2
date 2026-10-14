"""2d packer: dinh dang pack, index ma hoa, xac minh."""
import hashlib
import os

import pytest

from core import packer
from core.crypto import Keys
from core.errors import IntegrityError


def build(keys, n=20):
    w = packer.PackWriter(keys)
    chunks = [os.urandom(1000 + i) if i % 2 else b"lap lai " * (300 + i) for i in range(n)]
    for c in chunks:
        cid = keys.chunk_id(c)
        w.add(cid, keys.encrypt_chunk(cid, c), len(c))
    pid, data, entries = w.finish()
    return pid, data, entries, chunks


def test_ghi_doc_xac_minh():
    k = Keys.generate("r")
    pid, data, entries, chunks = build(k)
    assert pid == hashlib.sha256(data).hexdigest()
    assert data[:8] == packer.HEADER and data[-8:] == packer.FOOTER_MAGIC
    n, index_len, ids = packer.parse_structure(data)            # khong can khoa
    assert n == len(chunks) and index_len == 28 + 48 * n
    assert ids == [k.chunk_id(c) for c in chunks]
    got = packer.verify_pack(data, pid, k)
    assert [k.decrypt_chunk(e.id, packer.blob_of(data, e), e.raw_length) for e in got] == chunks


@pytest.mark.parametrize("where", ["header", "blob", "index", "idtable", "footer", "cuoi"])
def test_sua_1_byte_bat_ky_deu_bi_phat_hien(where):
    k = Keys.generate("r")
    pid, data, entries, _ = build(k)
    n = len(entries)
    pos = {"header": 3, "blob": entries[n // 2].offset + 20,
           "index": len(data) - 16 - 32 * n - 40, "idtable": len(data) - 16 - 32 * n + 5,
           "footer": len(data) - 12, "cuoi": len(data) - 1}[where]
    bad = bytearray(data)
    bad[pos] ^= 0x01
    with pytest.raises(IntegrityError):
        packer.verify_pack(bytes(bad), pid, k)                    # SHA-256 ten
    with pytest.raises(IntegrityError):                          # ke ca khi bo qua SHA: cau truc/GCM
        packer.verify_pack(bytes(bad), hashlib.sha256(bad).hexdigest(), k)


def test_sai_khoa_khong_doc_duoc_index():
    k = Keys.generate("r")
    pid, data, _, _ = build(k)
    with pytest.raises(IntegrityError):
        packer.read_index(Keys.generate("r"), data)


def test_dong_pack_theo_kich_thuoc_muc_tieu():
    k = Keys.generate("r")
    w = packer.PackWriter(k, target=10_000)
    blob = k.encrypt_chunk(k.chunk_id(os.urandom(4000)), os.urandom(4000))
    assert not w.would_overflow(len(blob))                        # pack rong luon nhan
    w.add(b"\x00" * 32, blob, 4000)
    w.add(b"\x01" * 32, blob, 4000)
    assert w.would_overflow(len(blob))
