"""
Cat mau theo noi dung (FastCDC, thu vien fastcdc==1.7.0 ban Cython) dang STREAM.

FastCDC chon diem cat cua mot mau chi dua vao toi da `max_size` byte tinh tu dau mau. Vi vay
chi can giu bo dem >= max_size byte phia truoc: mau nao co (offset + max_size) nam trong bo dem
(hoac da het file) thi diem cat chac chan giong het khi cat ca file mot lan. Phan con lai doi
doc them. RAM toi da ~ read_size (mac dinh max(4 x max_size, 16 MiB)).
"""
import os
from dataclasses import asdict, dataclass

from fastcdc import fastcdc as _fastcdc

from shared.snapshot import long_path

ALGORITHM = "fastcdc-1.7.0"
KiB, MiB = 1024, 1024 * 1024


@dataclass(frozen=True)
class ChunkerParams:
    min_size: int = 512 * KiB
    avg_size: int = 1 * MiB
    max_size: int = 8 * MiB

    def __post_init__(self):
        if not (64 <= self.min_size <= self.avg_size <= self.max_size):
            raise ValueError("Can 64 <= min <= avg <= max")
        if self.avg_size < 256 or self.max_size < 1024:
            raise ValueError("avg >= 256 va max >= 1024 (gioi han cua fastcdc)")

    def to_dict(self):
        return {"algorithm": ALGORITHM, **asdict(self)}

    @classmethod
    def from_dict(cls, d):
        if d.get("algorithm", ALGORITHM) != ALGORITHM:
            raise ValueError(f"Thuật toán cắt mẩu không hỗ trợ: {d.get('algorithm')}")
        return cls(int(d["min_size"]), int(d["avg_size"]), int(d["max_size"]))


READ_STEP = 4 * MiB


def iter_chunks(f, params=ChunkerParams(), read_size=None, size_hint=None):
    """Sinh lan luot cac mau (bytes) tu file-like `f` (che do nhi phan).
    size_hint: kich thuoc file (neu biet) -> khong xin bo dem lon hon can thiet.
    (FileIO.read(n) cap phat ngay n byte: doc file 8 KB bang read(32 MiB) rat cham tren Windows.)"""
    read_size = read_size or max(4 * params.max_size, 16 * MiB)
    buf = bytearray()
    eof = False
    total = 0
    while True:
        while not eof and len(buf) < read_size:
            want = min(read_size - len(buf), READ_STEP)
            if size_hint is not None:
                want = min(want, max(64 * KiB, size_hint - total + 1))
            b = f.read(want)
            if not b:
                eof = True
            else:
                buf += b
                total += len(b)
        if not buf:
            return
        consumed = 0
        mv = memoryview(buf)
        try:
            for c in _fastcdc(mv, params.min_size, params.avg_size, params.max_size):
                if not eof and c.offset + params.max_size > len(buf):
                    break                       # diem cat chua chac chan -> doc them
                yield bytes(mv[c.offset:c.offset + c.length])
                consumed = c.offset + c.length
        finally:
            mv.release()
        del buf[:consumed]
        if eof and not buf:
            return


def chunk_file(path, params=ChunkerParams()):
    with open(long_path(path), "rb", buffering=0) as f:
        yield from iter_chunks(f, params, size_hint=os.fstat(f.fileno()).st_size)


def chunk_bytes(data, params=ChunkerParams()):
    """Tien ich cho test: cat ca bo dem trong RAM (khong stream)."""
    return [bytes(memoryview(data)[c.offset:c.offset + c.length])
            for c in _fastcdc(memoryview(data), params.min_size, params.avg_size, params.max_size)]
