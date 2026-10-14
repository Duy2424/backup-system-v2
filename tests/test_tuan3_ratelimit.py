"""Test 3d: token bucket + lich 2 muc, dong ho gia (khong ngu that), sai so toc do <= 10%."""
from datetime import datetime, timedelta

import pytest

from core.ratelimit import RateLimiter, Schedule, parse_rate

MB = 1024 * 1024
GIO_HANH_CHINH = [{"thu": [2, 3, 4, 5, 6], "tu": "08:00", "den": "17:30", "toc_do": "2MB/s"}]


class FakeClock:
    def __init__(self, start):
        self.t0, self.elapsed = start, 0.0

    def now(self):
        return self.t0 + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    def sleep(self, s):
        assert s >= 0
        self.elapsed += s


def limiter(clock, schedule=None, rate=None):
    return RateLimiter(schedule, rate, now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)


def send(lim, total, piece=64 * 1024):
    while total > 0:
        n = min(piece, total)
        lim.consume(n)
        total -= n


def test_parse_rate():
    assert parse_rate("2MB/s") == 2 * MB and parse_rate("512KB/s") == 512 * 1024
    assert parse_rate(None) is None and parse_rate("0") is None and parse_rate(1000) == 1000
    with pytest.raises(ValueError):
        parse_rate("nhanh")


def test_toc_do_trung_binh_trong_10_phan_tram():
    c = FakeClock(datetime(2026, 10, 14, 10, 0))                      # thu Tu, gio hanh chinh
    lim = limiter(c, Schedule(GIO_HANH_CHINH))
    send(lim, 40 * MB)
    rate = 40 * MB / c.elapsed
    print(f"\n[3d] 40 MB trong {c.elapsed:.2f} s gia lap -> {rate / MB:.2f} MB/s (gioi han 2 MB/s)")
    assert abs(rate - 2 * MB) / (2 * MB) <= 0.10


def test_ngoai_gio_va_cuoi_tuan_khong_gioi_han():
    for start in (datetime(2026, 10, 14, 18, 0), datetime(2026, 10, 18, 10, 0)):     # 18h thu Tu, Chu Nhat
        c = FakeClock(start)
        send(limiter(c, Schedule(GIO_HANH_CHINH)), 100 * MB)
        assert c.elapsed == 0


def test_doi_muc_ngay_khi_qua_moc_gio():
    c = FakeClock(datetime(2026, 10, 14, 17, 29, 50))                 # con 10 s nua het gio hanh chinh
    send(limiter(c, Schedule(GIO_HANH_CHINH)), 200 * MB)
    # 10 s dau ~20 MB o 2 MB/s, phan con lai khong gioi han -> xong ngay sau moc 17:30
    assert 10 <= c.elapsed <= 10.5
    c2 = FakeClock(datetime(2026, 10, 14, 7, 59, 58))                 # sap vao gio: 2 s dau khong gioi han
    send(limiter(c2, Schedule(GIO_HANH_CHINH)), 6 * MB)
    assert c2.elapsed == 0 or c2.now() >= datetime(2026, 10, 14, 8, 0)


def test_toc_do_co_dinh_va_file_cau_hinh(tmp_path):
    c = FakeClock(datetime(2026, 10, 14, 10, 0))
    send(limiter(c, rate="1MB/s"), 5 * MB)
    assert 4.5 <= c.elapsed <= 5.5
    f = tmp_path / "gioi_han.json"
    f.write_text('{"mac_dinh": "8MB/s", "khung_gio": [{"thu": [2], "tu": "00:00", "den": "24:00", "toc_do": null}]}',
                 encoding="utf-8")
    s = Schedule.load(f)
    assert s.rate_at(datetime(2026, 10, 12, 12, 0)) is None            # Thu Hai: khong gioi han
    assert s.rate_at(datetime(2026, 10, 13, 12, 0)) == 8 * MB          # ngay khac: mac dinh
