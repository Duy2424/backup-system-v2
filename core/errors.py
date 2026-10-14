"""Loi cua loi v2."""


class CoreError(Exception):
    """Goc cua moi loi trong core."""


class IntegrityError(CoreError):
    """Du lieu khong xac thuc duoc: bi sua, bi hong, bi cat, hoac sai khoa. KHONG duoc dung du lieu."""


class WrongPassword(CoreError):
    """Mat khau khong mo duoc key file nao cua kho."""


class RepoError(CoreError):
    """Kho khong hop le / sai phien ban / thao tac khong cho phep."""


class NotFound(RepoError):
    """Khong co doi tuong (pack, snapshot, key, config)."""


class Cancelled(CoreError):
    """Nguoi dung huy giua chung."""
