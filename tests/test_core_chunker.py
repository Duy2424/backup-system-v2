"""2b chunker: FastCDC stream phai cho ket qua giong het cat ca bo dem."""
import io
import os
import random

import pytest

from core.chunker import ChunkerParams, chunk_bytes, iter_chunks
from tests.core_helpers import SMALL


def rand(n, seed=1):
    return random.Random(seed).randbytes(n)


@pytest.mark.parametrize("size", [0, 1, 100, 2048, 70_000, 1_000_003])
@pytest.mark.parametrize("read_size", [64 * 1024 + 1, 200_000, None])
def test_stream_giong_cat_ca_file(size, read_size):
    data = rand(size, size)
    ref = chunk_bytes(data, SMALL)
    got = list(iter_chunks(io.BytesIO(data), SMALL, read_size=read_size))
    assert got == ref
    assert b"".join(got) == data


def test_tham_so_mac_dinh_tren_du_lieu_lon():
    data = rand(24 * 1024 * 1024, 7)
    p = ChunkerParams()
    got = list(iter_chunks(io.BytesIO(data), p))           # read_size mac dinh 32 MiB > du lieu
    assert got == chunk_bytes(data, p)
    got2 = list(iter_chunks(io.BytesIO(data), p, read_size=9 * 1024 * 1024))   # buoc phai doc nhieu lan
    assert got2 == got
    assert all(p.min_size <= len(c) <= p.max_size for c in got[:-1])


@pytest.mark.parametrize("hint", [None, 0, 1000, 333_333, 10 ** 9])
def test_size_hint_sai_van_dung(hint):
    """size_hint chi de tranh cap phat bo dem lon; hint sai (file doi khi dang doc) khong lam sai ket qua."""
    data = rand(333_333, 9)
    assert list(iter_chunks(io.BytesIO(data), SMALL, read_size=100_000, size_hint=hint)) == chunk_bytes(data, SMALL)


def test_file_rong_va_file_nho():
    assert list(iter_chunks(io.BytesIO(b""), SMALL)) == []
    assert list(iter_chunks(io.BytesIO(b"abc"), SMALL)) == [b"abc"]


def test_chen_giua_file_chi_doi_vai_mau():
    data = rand(2_000_000, 3)
    a = chunk_bytes(data, SMALL)
    mid = len(data) // 2
    b = chunk_bytes(data[:mid] + b"CHEN-THEM" * 11 + data[mid:], SMALL)
    moi = set(b) - set(a)
    assert len(moi) <= 3 < len(b)          # FastCDC tu dong bo lai ngay sau cho chen


def test_tham_so_sai():
    with pytest.raises(ValueError):
        ChunkerParams(1024, 512, 4096)
