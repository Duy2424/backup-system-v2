"""
Ma hoa file backup.

Dinh dang moi "BKP2" (mac dinh): AES-256-GCM theo DOAN 1 MiB (kieu STREAM):
  header 16 byte = b"BKP2" | version=1 | seg_exp=20 | 2 byte 0 | nonce_prefix 8 byte
  doan i         = AESGCM(key, nonce = prefix || i (u32 big-endian),
                          plaintext <= 1 MiB, AAD = header || co_cuoi (1 byte))
- Moi doan co tag xac thuc: sua 1 byte -> loi InvalidTag, khong tra du lieu sai.
- Co "doan cuoi" trong AAD: cat bot duoi file -> phat hien duoc.
- Ma hoa/giai ma dang stream, khong nap ca file vao RAM.

Dinh dang cu "BKUP" (v1 goc: AES-256-CBC, padding 0, KHONG xac thuc) van giai ma
duoc de khoi phuc cac ban backup cu.

Khoa: chuoi Fernet cua user (CSDL server). BKP2 dung HKDF-SHA256, BKUP dung SHA-256.
"""
import io
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC_V2 = b"BKP2"
MAGIC_V1 = b"BKUP"
SEG_EXP = 20
SEG_SIZE = 1 << SEG_EXP          # 1 MiB plaintext moi doan
TAG = 16
HEADER_LEN = 16


class IntegrityError(ValueError):
    """Du lieu backup bi sua/hong hoac sai khoa."""


def _key_v2(key_str):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"backup-system bkp2 v1").derive(key_str.encode("utf-8"))


def _key_v1(key_str):
    digest = hashes.Hash(hashes.SHA256())
    digest.update(key_str.encode("utf-8"))
    return digest.finalize()


# ===================================================================== ghi

class EncryptWriter(io.RawIOBase):
    """File-like chi ghi: moi byte ghi vao duoc ma hoa roi day xuong `sink.write`."""

    def __init__(self, sink, key_str):
        super().__init__()
        self._sink = sink
        self._aead = AESGCM(_key_v2(key_str))
        self._prefix = os.urandom(8)
        self._header = MAGIC_V2 + bytes([1, SEG_EXP, 0, 0]) + self._prefix
        self._buf = bytearray()
        self._counter = 0
        self.plain_bytes = 0
        self.cipher_bytes = 0
        self._emit(self._header)

    def writable(self):
        return True

    def _emit(self, data):
        self._sink.write(data)
        self.cipher_bytes += len(data)

    def _seal(self, data, last):
        if self._counter >= 2 ** 32:
            raise OverflowError("Qua nhieu doan")
        nonce = self._prefix + struct.pack(">I", self._counter)
        self._counter += 1
        self._emit(self._aead.encrypt(nonce, bytes(data), self._header + (b"\x01" if last else b"\x00")))

    def write(self, b):
        if self.closed:
            raise ValueError("write tren writer da dong")
        self._buf += b
        self.plain_bytes += len(b)
        # Giu lai toi thieu 1 byte de doan cuoi khong bao gio rong tru khi file rong
        while len(self._buf) > SEG_SIZE:
            self._seal(self._buf[:SEG_SIZE], last=False)
            del self._buf[:SEG_SIZE]
        return len(b)

    def close(self):
        if not self.closed:
            self._seal(self._buf, last=True)
            self._buf = bytearray()
            super().close()

    def abandon(self):
        """Dong ma KHONG ghi doan cuoi (khi pipeline loi) - file khong bao gio hop le."""
        self._buf = bytearray()
        io.RawIOBase.close(self)


# ===================================================================== doc

class _DecryptV2(io.RawIOBase):
    def __init__(self, src, key_str, header):
        super().__init__()
        self._src = src
        self._aead = AESGCM(_key_v2(key_str))
        self._header = header
        self._prefix = header[8:16]
        self._counter = 0
        self._pending = self._read_exact(SEG_SIZE + TAG)
        self._out = b""
        self._pos = 0
        self._done = False
        if not self._pending:
            raise IntegrityError("File backup bi cat cut (thieu doan cuoi)")

    def _read_exact(self, n):
        parts, got = [], 0
        while got < n:
            b = self._src.read(n - got)
            if not b:
                break
            parts.append(b)
            got += len(b)
        return b"".join(parts)

    def readable(self):
        return True

    def _next_segment(self):
        cur = self._pending
        nxt = self._read_exact(SEG_SIZE + TAG)
        last = not nxt
        if not last and len(cur) != SEG_SIZE + TAG:
            raise IntegrityError("Cau truc doan khong hop le")
        nonce = self._prefix + struct.pack(">I", self._counter)
        try:
            plain = self._aead.decrypt(nonce, cur, self._header + (b"\x01" if last else b"\x00"))
        except InvalidTag:
            raise IntegrityError(f"Doan {self._counter} khong xac thuc duoc "
                                 f"(file bi sua/hong, bi cat hoac sai khoa)") from None
        self._counter += 1
        self._pending = nxt
        self._done = last
        return plain

    def readinto(self, b):
        while self._pos >= len(self._out):
            if self._done:
                return 0
            self._out, self._pos = self._next_segment(), 0
        n = min(len(b), len(self._out) - self._pos)
        b[:n] = self._out[self._pos:self._pos + n]
        self._pos += n
        return n


class _DecryptV1(io.RawIOBase):
    """Dinh dang cu: magic | size u64 | IV 16 | AES-CBC (padding 0). Khong co xac thuc."""

    def __init__(self, src, key_str):
        super().__init__()
        self._src = src
        size_raw, iv = src.read(8), src.read(16)
        if len(size_raw) != 8 or len(iv) != 16:
            raise IntegrityError("Header BKUP khong day du")
        self._left = struct.unpack("<Q", size_raw)[0]
        self._dec = Cipher(algorithms.AES(_key_v1(key_str)), modes.CBC(iv)).decryptor()
        self._out = b""
        self._pos = 0
        self._eof = False

    def readable(self):
        return True

    def readinto(self, b):
        while self._pos >= len(self._out):
            if self._eof or self._left <= 0:
                return 0
            chunk = self._src.read(1024 * 1024)
            if not chunk:
                plain = self._dec.finalize()
                self._eof = True
            else:
                plain = self._dec.update(chunk)
            plain = plain[:self._left]
            self._left -= len(plain)
            self._out, self._pos = plain, 0
        n = min(len(b), len(self._out) - self._pos)
        b[:n] = self._out[self._pos:self._pos + n]
        self._pos += n
        return n


def open_decrypt_stream(src, key_str):
    """Tra ve file-like doc plaintext (tu nhan dien BKP2 / BKUP cu)."""
    magic = src.read(4)
    if magic == MAGIC_V2:
        rest = src.read(HEADER_LEN - 4)
        header = magic + rest
        if len(header) != HEADER_LEN or header[4] != 1 or header[5] != SEG_EXP:
            raise IntegrityError("Header BKP2 khong hop le / phien ban khong ho tro")
        raw = _DecryptV2(src, key_str, header)
    elif magic == MAGIC_V1:
        raw = _DecryptV1(src, key_str)
    else:
        raise IntegrityError("Khong phai file backup (.bkup) hop le")
    return io.BufferedReader(raw, buffer_size=SEG_SIZE)


# ===================================================================== tien ich file

def encrypt_file(in_path, out_path, key_str):
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        w = EncryptWriter(fout, key_str)
        for block in iter(lambda: fin.read(SEG_SIZE), b""):
            w.write(block)
        w.close()


def decrypt_file(in_path, out_path, key_str):
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        r = open_decrypt_stream(fin, key_str)
        for block in iter(lambda: r.read(SEG_SIZE), b""):
            fout.write(block)


def encrypt_file_legacy(in_path, out_path, key_str):
    """Ghi theo dinh dang v1 goc (CHI dung cho test tuong thich)."""
    iv = os.urandom(16)
    enc = Cipher(algorithms.AES(_key_v1(key_str)), modes.CBC(iv)).encryptor()
    size = os.path.getsize(in_path)
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        fout.write(MAGIC_V1 + struct.pack("<Q", size) + iv)
        for chunk in iter(lambda: fin.read(SEG_SIZE), b""):
            if len(chunk) % 16:
                chunk += b"\x00" * (16 - len(chunk) % 16)
            fout.write(enc.update(chunk))
        fout.write(enc.finalize())


def encrypt_bytes(data, key_str):
    """Ma hoa du lieu nho (Fernet)."""
    return Fernet(key_str.encode() if isinstance(key_str, str) else key_str).encrypt(data)


def decrypt_bytes(data, key_str):
    return Fernet(key_str.encode() if isinstance(key_str, str) else key_str).decrypt(data)
