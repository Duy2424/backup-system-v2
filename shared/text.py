"""Dinh dang so kieu Viet Nam cho thong bao hien tren web: 1.256 file, 78,0 MB."""


def vn_int(n):
    return f"{int(n):,}".replace(",", ".")


def vn_num(x, decimals=1):
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def vn_mb(nbytes, decimals=1):
    return f"{vn_num(nbytes / 1048576, decimals)} MB"
