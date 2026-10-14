"""
Client HTTP cua API kho (docs/repo-format.md muc 10). Cung giao dien voi LocalRepo.

  POST /chunks/missing   PUT /packs/<id>   GET /packs/<id> (Range)   PUT /snapshots/<id>
  GET /snapshots  GET /snapshots/<id>  POST /chunks/locate  GET|PUT /config  GET /keys  GET|PUT /keys/<id>

- mTLS: cert/key = chung chi client (Caddy cua Nguoi B doi), ca = CA de xac minh server.
- Thu lai co backoff (1, 2, 4, ... toi da 60 s) khi loi mang hoac 429/500/502/503/504.
  KHONG thu lai loi TLS (sai chung chi khong tu het) va cac 4xx khac.
- Gioi han toc do: limiter.consume() cho moi 64 KiB gui di (PUT pack/snapshot).
- Khong co lenh xoa.
"""
import logging
import time

import requests

from core import FORMAT_VERSION, packer
from core.backend import Backend
from core.errors import IntegrityError, NotFound, RepoError

log = logging.getLogger("core.http")
RETRY_STATUS = {429, 500, 502, 503, 504}
PIECE = 64 * 1024


class _LimitedBody:
    """Than request stream tung 64 KiB qua bo gioi han toc do. Co __len__ nen requests gui
    Content-Length that (API kho bat buoc) thay vi Transfer-Encoding: chunked."""

    def __init__(self, data, limiter):
        self.data, self.limiter = data, limiter

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        for i in range(0, len(self.data), PIECE):
            piece = self.data[i:i + PIECE]
            if self.limiter:
                self.limiter.consume(len(piece))
            yield piece


class HttpRepo(Backend):
    def __init__(self, base_url, cert=None, key=None, ca=None, timeout=(10, 120), retries=6,
                 backoff=1.0, limiter=None, sleep=time.sleep):
        self.base = base_url.rstrip("/")
        self.timeout, self.retries, self.backoff = timeout, retries, backoff
        self.limiter, self.sleep = limiter, sleep
        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"backup-system-v2/{FORMAT_VERSION}"
        if cert:
            self.s.cert = (cert, key) if key else cert
        if ca:
            self.s.verify = ca
        self.bytes_sent = 0
        self.bytes_received = 0

    def describe(self):
        return self.base

    # ------------------------------------------------------------ goi + thu lai
    def _error(self, r):
        try:
            d = r.json()
            code, msg = d.get("error", ""), d.get("message", r.text[:200])
        except ValueError:
            code, msg = "", r.text[:200]
        text = f"{r.request.method} {r.url} -> {r.status_code} {code}: {msg}"
        if r.status_code == 404:
            return NotFound(text)
        if r.status_code == 400 and code in ("hash_mismatch", "bad_pack", "bad_snapshot"):
            return IntegrityError(text)
        if r.status_code in (401, 403):
            return RepoError(f"Bị từ chối ({text}) - kiểm tra chứng chỉ client / quyền truy cập")
        return RepoError(text)

    def _req(self, method, path, ok=(200,), body=None, json_body=None, headers=None):
        url = self.base + path
        last = None
        for attempt in range(self.retries + 1):
            try:
                data = body() if callable(body) else body
                r = self.s.request(method, url, data=data, json=json_body, headers=headers, timeout=self.timeout)
            except requests.exceptions.SSLError as e:
                raise RepoError(f"Lỗi TLS/mTLS với {self.base}: {e}") from None
            except (requests.ConnectionError, requests.Timeout) as e:
                last = f"mất kết nối: {e.__class__.__name__}"
            else:
                if r.status_code in ok:
                    self.bytes_received += len(r.content)
                    return r
                if r.status_code not in RETRY_STATUS:
                    raise self._error(r)
                last = f"HTTP {r.status_code}"
            if attempt == self.retries:
                raise RepoError(f"{method} {path}: thất bại sau {self.retries + 1} lần thử ({last})")
            delay = min(self.backoff * (2 ** attempt), 60)
            log.warning("%s %s lỗi (%s) - thử lại sau %.1f s (lần %d/%d)", method, path, last, delay,
                        attempt + 1, self.retries)
            self.sleep(delay)

    def _put_bytes(self, path, data):
        r = self._req("PUT", path, ok=(200, 201), body=lambda: _LimitedBody(data, self.limiter),
                      headers={"Content-Type": "application/octet-stream"})
        self.bytes_sent += len(data)
        return (r.json() or {}).get("status", "created" if r.status_code == 201 else "exists")

    # ------------------------------------------------------------ 4 lenh chinh
    def missing_chunks(self, ids):
        ids = list(ids)
        if not ids:
            return []
        return self._req("POST", "/chunks/missing", json_body={"ids": ids}).json()["missing"]

    def put_pack(self, pack_id, data):
        if not packer.is_hex_id(pack_id):
            raise RepoError(f"pack_id không hợp lệ: {pack_id!r}")
        return self._put_bytes(f"/packs/{pack_id}", data)

    def get_pack(self, pack_id, start=None, end=None):
        headers = None
        if start is not None:
            headers = {"Range": f"bytes={start}-" + ("" if end is None else str(end - 1))}
        return self._req("GET", f"/packs/{pack_id}", ok=(200, 206), headers=headers).content

    def get_pack_tail(self, pack_id, n):
        r = self._req("GET", f"/packs/{pack_id}", ok=(200, 206), headers={"Range": f"bytes=-{int(n)}"})
        return r.content[-n:]          # server khong ho tro Range (200) -> van dung

    def put_snapshot(self, snapshot_id, data):
        return self._put_bytes(f"/snapshots/{snapshot_id}", data)

    # ------------------------------------------------------------ lenh doc bo sung
    def list_snapshots(self):
        return self._req("GET", "/snapshots").json()["snapshots"]

    def get_snapshot(self, snapshot_id):
        return self._req("GET", f"/snapshots/{snapshot_id}").content

    def locate_chunks(self, ids):
        ids = list(ids)
        if not ids:
            return {}
        return self._req("POST", "/chunks/locate", json_body={"ids": ids}).json()["locations"]

    def get_config(self):
        return self._req("GET", "/config").content

    def put_config(self, data):
        return self._put_bytes("/config", data)

    def list_keys(self):
        return self._req("GET", "/keys").json()["keys"]

    def get_key(self, key_id):
        return self._req("GET", f"/keys/{key_id}").content

    def put_key(self, key_id, data):
        return self._put_bytes(f"/keys/{key_id}", data)
