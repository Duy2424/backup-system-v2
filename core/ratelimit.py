"""
Gioi han toc do gui (token bucket) theo lich 2 muc.

File cau hinh JSON (vd config\\gioi_han_toc_do.json):
  {
    "mac_dinh": null,                                   // ngoai cac khung gio: khong gioi han
    "khung_gio": [
      {"thu": [2, 3, 4, 5, 6], "tu": "08:00", "den": "17:30", "toc_do": "2MB/s"}
    ]
  }
  thu: 2 = Thu Hai ... 7 = Thu Bay, 8 = Chu Nhat (cach goi Viet Nam). toc_do: "2MB/s", "512KB/s",
  so byte/giay, hoac null = khong gioi han.

Muc gioi han doi NGAY khi qua moc gio: consume() chia luong lon thanh phan nho va hoi lai
toc do hien hanh truoc moi phan. Dong ho (now/monotonic/sleep) tiem vao duoc -> test khong
can ngu that.
"""
import json
import re
import time
from datetime import datetime

_UNITS = {"": 1, "B": 1, "KB": 1024, "KIB": 1024, "MB": 1024 ** 2, "MIB": 1024 ** 2, "GB": 1024 ** 3, "GIB": 1024 ** 3}


def parse_rate(v):
    """'2MB/s' -> 2097152; None/0/'' -> None (khong gioi han)."""
    if v in (None, "", 0, "0"):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    m = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]*)\s*(/s)?\s*", str(v))
    if not m or m.group(2).upper() not in _UNITS:
        raise ValueError(f"Toc do khong hop le: {v!r} (vd 2MB/s)")
    r = float(m.group(1)) * _UNITS[m.group(2).upper()]
    return r if r > 0 else None


def _hm(s):
    h, m = str(s).split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 24 and 0 <= m < 60):
        raise ValueError(f"Gio khong hop le: {s}")
    return h * 60 + m


class Schedule:
    def __init__(self, rules=(), default=None):
        self.default = parse_rate(default)
        self.rules = []
        for r in rules:
            days = {int(d) for d in r["thu"]}
            if not days <= set(range(2, 9)):
                raise ValueError("thu phai trong 2..8 (8 = Chu Nhat)")
            self.rules.append((days, _hm(r["tu"]), _hm(r["den"]), parse_rate(r.get("toc_do"))))

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        return cls(d.get("khung_gio", []), d.get("mac_dinh"))

    def rate_at(self, when):
        """Toc do (byte/giay) tai thoi diem `when`; None = khong gioi han."""
        thu = when.isoweekday() + 1            # Mon=1 -> "Thu 2"; Sun=7 -> 8
        minute = when.hour * 60 + when.minute
        for days, start, end, rate in self.rules:
            if thu in days and start <= minute < end:
                return rate
        return self.default


class RateLimiter:
    """Token bucket: dung luong = 1 giay o toc do hien hanh (cho phep burst ngan)."""

    def __init__(self, schedule=None, rate=None, now=datetime.now, monotonic=time.monotonic, sleep=time.sleep):
        self.schedule = schedule
        self.fixed = parse_rate(rate)
        self.now, self.monotonic, self.sleep = now, monotonic, sleep
        self.tokens = 0.0
        self.last = monotonic()
        self.rate = None

    def current_rate(self):
        return self.schedule.rate_at(self.now()) if self.schedule else self.fixed

    def consume(self, n):
        """Doi den khi duoc phep gui them n byte."""
        while n > 0:
            rate = self.current_rate()
            t = self.monotonic()
            if rate != self.rate:                  # vua qua moc gio: ap muc moi ngay
                self.rate, self.tokens = rate, 0.0
                self.last = t
            if rate is None:
                return
            self.tokens = min(rate, self.tokens + (t - self.last) * rate)
            self.last = t
            piece = min(n, max(1.0, rate / 4))     # phan nho -> doi muc kip thoi
            if self.tokens >= piece:
                self.tokens -= piece
                n -= piece
                continue
            self.sleep((piece - self.tokens) / rate)        # <= 0,25 s -> qua moc gio la doi muc ngay
