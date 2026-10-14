"""
Giao dien backend kho (docs/repo-format.md muc 10). RepoLocal (thu muc) va client HTTP (tuan 3)
cung cai dat cac ham nay, nen tang tren (repository.py) khong biet kho o dau.

ID (chunk, pack, snapshot, key) luon la chuoi hex thuong 64 ky tu.
KHONG co ham xoa. Moi ham put_* khong ghi de: da co -> tra ve "exists".
"""
from abc import ABC, abstractmethod


class Backend(ABC):
    # ---- 4 lenh chinh (muc 10.1)
    @abstractmethod
    def missing_chunks(self, ids):
        """ids: list hex -> list hex chua co (giu thu tu, bo trung)."""

    @abstractmethod
    def put_pack(self, pack_id, data):
        """-> "created" | "exists". Kho kiem tra SHA-256 + cau truc."""

    @abstractmethod
    def get_pack(self, pack_id, start=None, end=None):
        """Byte cua pack (hoac doan [start, end) neu co)."""

    def get_pack_tail(self, pack_id, n):
        """n byte CUOI cua pack (HTTP: Range: bytes=-n). Dung de doc index ma khong tai ca pack."""
        return self.get_pack(pack_id)[-n:]

    @abstractmethod
    def put_snapshot(self, snapshot_id, data):
        """-> "created" | "exists". Luon goi SAU CUNG."""

    # ---- lenh doc / ghi-mot-lan bo sung (muc 10.2)
    @abstractmethod
    def list_snapshots(self):
        """-> [{"id", "size", "mtime"}]"""

    @abstractmethod
    def get_snapshot(self, snapshot_id):
        ...

    @abstractmethod
    def locate_chunks(self, ids):
        """-> {chunk_id: pack_id} cho cac ID co trong kho."""

    @abstractmethod
    def get_config(self):
        ...

    @abstractmethod
    def put_config(self, data):
        ...

    @abstractmethod
    def list_keys(self):
        ...

    @abstractmethod
    def get_key(self, key_id):
        ...

    @abstractmethod
    def put_key(self, key_id, data):
        ...

    # ---- tuy chon (check day du)
    def list_packs(self):
        raise NotImplementedError

    def describe(self):
        return self.__class__.__name__
