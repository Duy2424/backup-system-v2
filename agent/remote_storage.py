"""
Giao tiep kho tren server (agent goi).

- upload_stream(): gui than request dang chunked tu 1 generator -> khong can file tam,
  khong nap ca ban backup vao RAM. Server ghi file tam roi doi ten, tra ve sha256.
- download_stream(): tra ve response dang stream de giai ma ngay khi tai.
- KHONG co ham xoa: kho chi cho them (chong ransomware).
"""
import hashlib
import logging

import requests

log = logging.getLogger("agent.storage")


class StorageError(RuntimeError):
    pass


class RemoteStorageClient:
    def __init__(self, server_url, token, timeout=(10, 300)):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["X-Auth-Token"] = token

    def _url(self, path):
        return f"{self.server_url}{path}"

    def ping(self):
        try:
            return self.session.get(self._url("/api/ping"), timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def upload_stream(self, filename, chunks):
        """
        Gui cac khoi bytes tu `chunks` len /api/storage/backups/<filename>.
        Tra ve {"size", "sha256"} va kiem tra khop voi phia server.
        """
        h = hashlib.sha256()
        sent = [0]

        def body():
            for c in chunks:
                if c:
                    h.update(c)
                    sent[0] += len(c)
                    yield c

        r = self.session.put(self._url(f"/api/storage/backups/{filename}"), data=body(),
                             headers={"Content-Type": "application/octet-stream"}, timeout=self.timeout)
        if r.status_code not in (200, 201):
            raise StorageError(f"Upload loi {r.status_code}: {r.text[:300]}")
        info = r.json()
        if info.get("sha256") != h.hexdigest() or info.get("size") != sent[0]:
            raise StorageError("Server nhan khong khop du lieu da gui (sha256/kich thuoc)")
        log.info("Upload xong %s (%s byte)", filename, f"{sent[0]:,}")
        return {"size": sent[0], "sha256": h.hexdigest()}

    def download_stream(self, filename):
        """Response stream (dung .raw de doc). Nho dong lai sau khi dung."""
        r = self.session.get(self._url(f"/api/storage/backups/{filename}"), stream=True, timeout=self.timeout)
        if r.status_code != 200:
            text = r.text[:300]
            r.close()
            raise StorageError(f"Tai ve loi {r.status_code}: {text}")
        r.raw.decode_content = False
        return r

    def list_files(self):
        r = self.session.get(self._url("/api/storage/backups"), timeout=30)
        r.raise_for_status()
        return r.json()
