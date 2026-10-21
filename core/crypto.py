"""
Khoa va ma hoa (docs/repo-format.md muc 3-5).

  chunk_id  = HMAC-SHA256(id_key, plaintext)                         32 byte
  payload   = type (0x00 raw | 0x01 zstd) || data                   zstd chi khi lam NHO hon
  blob      = nonce(12) || AES-256-GCM(enc_key, nonce, payload, AAD = chunk_id) || tag(16)
  key file  = JSON: scrypt(mat khau) -> KEK, KEK boc {"repo_id","enc_key","id_key"} bang AES-GCM
  key_id    = SHA-256(byte cua key file)

Giai ma mau: GCM xac thuc + tinh lai HMAC so voi chunk ID (kiem tra kep).
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import platform
from datetime import datetime

import zstandard
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from core.errors import IntegrityError, RepoError, WrongPassword

KEYFILE_AAD = b"BSV2KEY\x01"
TYPE_RAW, TYPE_ZSTD = 0, 1
NONCE, TAG = 12, 16
SCRYPT_DEFAULT = {"n": 2 ** 15, "r": 8, "p": 1}
ZSTD_LEVEL = 3


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _unb64(s):
    return base64.b64decode(s.encode("ascii"), validate=True)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


class Keys:
    """Khoa chu cua kho + cac thao tac ma hoa. Khong dung chung giua cac thread."""

    def __init__(self, enc_key, id_key, repo_id, compress=True, zstd_level=ZSTD_LEVEL):
        if len(enc_key) != 32 or len(id_key) != 32:
            raise ValueError("enc_key va id_key phai 32 byte")
        self.enc_key, self.id_key, self.repo_id = enc_key, id_key, repo_id
        self._aead = AESGCM(enc_key)
        self.compress = compress
        self._zc = zstandard.ZstdCompressor(level=zstd_level)
        self._zd = zstandard.ZstdDecompressor()

    def set_compression(self, level):
        """level 0 = khong nen; 1..22 = muc zstd (theo config cua kho)."""
        self.compress = level > 0
        self._zc = zstandard.ZstdCompressor(level=max(int(level), 1))

    @classmethod
    def generate(cls, repo_id):
        return cls(os.urandom(32), os.urandom(32), repo_id)

    # ------------------------------------------------------------ chung
    def seal(self, plaintext, aad):
        nonce = os.urandom(NONCE)
        return nonce + self._aead.encrypt(nonce, plaintext, aad)

    def open(self, data, aad, what="du lieu"):
        if len(data) < NONCE + TAG:
            raise IntegrityError(f"{what}: quá ngắn")
        try:
            return self._aead.decrypt(data[:NONCE], data[NONCE:], aad)
        except InvalidTag:
            raise IntegrityError(f"{what}: không xác thực được (bị sửa/hỏng hoặc sai khoá)") from None

    # ------------------------------------------------------------ mau
    def chunk_id(self, data):
        return hmac.new(self.id_key, data, hashlib.sha256).digest()

    def encrypt_chunk(self, cid, data):
        payload = None
        if self.compress and len(data) >= 64:
            z = self._zc.compress(data)
            if len(z) < len(data):
                payload = bytes([TYPE_ZSTD]) + z
        if payload is None:
            payload = bytes([TYPE_RAW]) + data
        return self.seal(payload, cid)

    def decrypt_chunk(self, cid, blob, raw_length=None):
        payload = self.open(blob, cid, f"mẩu {cid.hex()[:12]}")
        kind, body = payload[0], payload[1:]
        if kind == TYPE_RAW:
            data = body
        elif kind == TYPE_ZSTD:
            try:
                data = self._zd.decompress(body, max_output_size=raw_length or 0)
            except zstandard.ZstdError as e:
                raise IntegrityError(f"mẩu {cid.hex()[:12]}: giải nén lỗi: {e}") from None
        else:
            raise IntegrityError(f"mẩu {cid.hex()[:12]}: kiểu payload lạ {kind}")
        if raw_length is not None and len(data) != raw_length:
            raise IntegrityError(f"mẩu {cid.hex()[:12]}: sai độ dài")
        if not hmac.compare_digest(self.chunk_id(data), cid):
            raise IntegrityError(f"mẩu {cid.hex()[:12]}: HMAC không khớp chunk ID")
        return data


# ================================================================ key file

def _kek(password, salt, n, r, p):
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def make_key_file(keys, password, scrypt=None, host=None, user=None):
    """Bytes cua key file (JSON) boc khoa chu bang mat khau."""
    if not password:
        raise ValueError("Mật khẩu không được rỗng")
    params = dict(SCRYPT_DEFAULT, **(scrypt or {}))
    salt, nonce = os.urandom(16), os.urandom(NONCE)
    inner = json.dumps({"repo_id": keys.repo_id, "enc_key": _b64(keys.enc_key),
                        "id_key": _b64(keys.id_key)}).encode("utf-8")
    wrapped = AESGCM(_kek(password, salt, **params)).encrypt(nonce, inner, KEYFILE_AAD)
    doc = {
        "version": 1,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": host or platform.node(),
        "user": user or getpass.getuser(),
        "kdf": {"name": "scrypt", **params, "salt": _b64(salt)},
        "wrap": {"cipher": "AES-256-GCM", "nonce": _b64(nonce), "data": _b64(wrapped)},
    }
    return json.dumps(doc, indent=1).encode("utf-8")


def open_key_file(data, password, compress=True):
    """Mo key file. Sai mat khau -> WrongPassword. Hong file -> RepoError."""
    try:
        doc = json.loads(data.decode("utf-8"))
        kdf, wrap = doc["kdf"], doc["wrap"]
        if doc.get("version") != 1 or kdf.get("name") != "scrypt" or wrap.get("cipher") != "AES-256-GCM":
            raise RepoError("Key file phiên bản/thuật toán không hỗ trợ")
        kek = _kek(password, _unb64(kdf["salt"]), int(kdf["n"]), int(kdf["r"]), int(kdf["p"]))
        nonce, wrapped = _unb64(wrap["nonce"]), _unb64(wrap["data"])
    except (ValueError, KeyError, TypeError) as e:
        raise RepoError(f"Key file hỏng: {e}") from None
    try:
        inner = json.loads(AESGCM(kek).decrypt(nonce, wrapped, KEYFILE_AAD))
    except InvalidTag:
        raise WrongPassword("Sai mật khẩu") from None
    return Keys(_unb64(inner["enc_key"]), _unb64(inner["id_key"]), inner["repo_id"], compress=compress)


def key_id(data):
    return sha256_hex(data)
