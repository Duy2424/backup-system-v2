"""
Pack: gom nhieu mau da ma hoa thanh 1 file (~16 MiB) - docs/repo-format.md muc 6.

  | 0       | 8          | "BSV2PK" 0x01 0x00                                          |
  | 8       | sum(blob)  | blob_1 || ... || blob_n                                     |
  | ...     | 28 + 48n   | index ma hoa: nonce || GCM(enc_key, index, AAD) || tag       |
  | ...     | 32n        | bang ID (ro), cung thu tu blob                               |
  | cuoi-16 | 16         | L (u32) || n (u32) || "BSV2PEND"                             |

  index      = n ban ghi "<32sQII": chunk_id | offset (tu dau pack) | do dai blob | do dai plaintext
  AAD index  = b"BSV2IDX\\x01" || bang ID   -> kho sua bang ID thi giai ma index se loi
  pack_id    = SHA-256(ca pack)

parse_structure() KHONG can khoa: kho (Nguoi B) dung de kiem tra pack nhan duoc (muc 6.3).
"""
import hashlib
import re
import struct
from dataclasses import dataclass

from core.errors import IntegrityError

HEADER = b"BSV2PK\x01\x00"
FOOTER_MAGIC = b"BSV2PEND"
INDEX_AAD = b"BSV2IDX\x01"
ENTRY = struct.Struct("<32sQII")        # 48 byte
FOOTER = struct.Struct("<II8s")         # 16 byte
ID_LEN = 32
MIN_BLOB = 12 + 2 + 16                  # nonce + (type + >=1 byte) + tag
MAX_PACK_SIZE = 64 * 1024 * 1024
MAX_CHUNKS = 1 << 20
DEFAULT_TARGET = 16 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def is_hex_id(s):
    return isinstance(s, str) and bool(HEX64.match(s))


@dataclass(frozen=True)
class IndexEntry:
    id: bytes
    offset: int
    length: int
    raw_length: int


class PackWriter:
    """Gom blob vao 1 pack. Dong pack khi them blob tiep theo se vuot `target`."""

    def __init__(self, keys, target=DEFAULT_TARGET):
        self.keys, self.target = keys, target
        self._parts = [HEADER]
        self._entries = []
        self._offset = len(HEADER)
        self.raw_bytes = 0

    def __len__(self):
        return len(self._entries)

    @property
    def size(self):
        return self._offset

    def would_overflow(self, blob_len):
        return bool(self._entries) and self._offset + blob_len > self.target

    def add(self, cid, blob, raw_length):
        if len(self._entries) >= MAX_CHUNKS:
            raise ValueError("Pack qua nhieu mau")
        self._entries.append(IndexEntry(cid, self._offset, len(blob), raw_length))
        self._parts.append(blob)
        self._offset += len(blob)
        self.raw_bytes += raw_length

    def finish(self):
        """Tra ve (pack_id_hex, bytes, entries)."""
        if not self._entries:
            raise ValueError("Pack rong")
        ids = b"".join(e.id for e in self._entries)
        index = b"".join(ENTRY.pack(e.id, e.offset, e.length, e.raw_length) for e in self._entries)
        enc_index = self.keys.seal(index, INDEX_AAD + ids)
        data = b"".join(self._parts) + enc_index + ids + FOOTER.pack(len(enc_index), len(self._entries), FOOTER_MAGIC)
        return hashlib.sha256(data).hexdigest(), data, list(self._entries)


# ================================================================ doc / kiem tra

def parse_footer(tail16, total_size=None):
    """(index_len, n) tu 16 byte cuoi. Kiem tra rang buoc kich thuoc (khong can khoa).
    total_size=None: chua biet kich thuoc pack (doc tung phan qua Range) -> bo qua kiem tra vung blob."""
    if len(tail16) != FOOTER.size:
        raise IntegrityError("pack: thiếu footer")
    index_len, n, magic = FOOTER.unpack(tail16)
    if magic != FOOTER_MAGIC:
        raise IntegrityError("pack: sai magic footer")
    if not 1 <= n <= MAX_CHUNKS or index_len != 28 + 48 * n:
        raise IntegrityError("pack: footer không hợp lệ")
    if total_size is not None:
        blob_region = total_size - len(HEADER) - index_len - ID_LEN * n - FOOTER.size
        if blob_region < MIN_BLOB * n:
            raise IntegrityError("pack: kích thước không khớp footer")
    return index_len, n


def read_index_from_tail(keys, tail):
    """Giai ma index tu PHAN DUOI pack (index ma hoa + bang ID + footer) - khong can ca pack."""
    index_len, n = parse_footer(tail[-FOOTER.size:])
    if len(tail) < index_len + ID_LEN * n + FOOTER.size:
        raise IntegrityError("pack: phần đuôi quá ngắn")
    ids_start = len(tail) - FOOTER.size - ID_LEN * n
    table = tail[ids_start:ids_start + ID_LEN * n]
    index = keys.open(tail[ids_start - index_len:ids_start], INDEX_AAD + table, "index pack")
    entries = [IndexEntry(*ENTRY.unpack_from(index, i * ENTRY.size)) for i in range(n)]
    pos = len(HEADER)
    for i, e in enumerate(entries):
        if e.id != table[i * ID_LEN:(i + 1) * ID_LEN] or e.offset != pos or e.length < MIN_BLOB:
            raise IntegrityError("pack: index không khớp bảng ID / vị trí")
        pos += e.length
    return entries


def tail_size(index_len, n):
    return index_len + ID_LEN * n + FOOTER.size


def parse_structure(data):
    """Kiem tra cau truc (muc 6.3, khong can khoa). Tra ve (n, index_len, [chunk_id bytes])."""
    if len(data) > MAX_PACK_SIZE:
        raise IntegrityError("pack: quá lớn")
    if len(data) < len(HEADER) + FOOTER.size or data[:len(HEADER)] != HEADER:
        raise IntegrityError("pack: sai header")
    index_len, n = parse_footer(data[-FOOTER.size:], len(data))
    ids_start = len(data) - FOOTER.size - ID_LEN * n
    table = data[ids_start:ids_start + ID_LEN * n]
    return n, index_len, [table[i:i + ID_LEN] for i in range(0, len(table), ID_LEN)]


def read_index(keys, data):
    """Giai ma + xac thuc index (ca bang ID). Tra ve danh sach IndexEntry."""
    n, index_len, ids = parse_structure(data)
    ids_start = len(data) - FOOTER.size - ID_LEN * n
    enc_index = data[ids_start - index_len:ids_start]
    index = keys.open(enc_index, INDEX_AAD + b"".join(ids), "index pack")
    entries = [IndexEntry(*ENTRY.unpack_from(index, i * ENTRY.size)) for i in range(n)]
    pos, end = len(HEADER), ids_start - index_len
    for e, cid in zip(entries, ids):
        if e.id != cid or e.offset != pos or e.length < MIN_BLOB:
            raise IntegrityError("pack: index không khớp bảng ID / vị trí")
        pos += e.length
    if pos != end:
        raise IntegrityError("pack: tổng độ dài blob không khớp")
    return entries


def blob_of(data, entry):
    return data[entry.offset:entry.offset + entry.length]


def verify_pack(data, pack_id, keys=None, read_data=True):
    """SHA-256 = ten; cau truc; (co khoa) index; (read_data) giai ma moi mau + HMAC."""
    if hashlib.sha256(data).hexdigest() != pack_id:
        raise IntegrityError(f"pack {pack_id[:12]}: SHA-256 không khớp tên (pack bị sửa/hỏng)")
    if keys is None:
        return parse_structure(data)[2]
    entries = read_index(keys, data)
    if read_data:
        for e in entries:
            keys.decrypt_chunk(e.id, blob_of(data, e), e.raw_length)
    return entries
