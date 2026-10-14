"""
Sinh bo du lieu mau TAT DINH cho benchmark v1/v2.

Cung --seed + --size => cung ten file, cung noi dung, cung mtime (kiem chung
bang --digest). Nho vay v1, v2, restic chay tren DUNG mot bo du lieu.

Thanh phan (ty le theo --size):
  40%  1 file lon        csdl/ban_hang.mdf   khoi 1 MiB: ngau nhien / ban ghi / vung trong
  20%  anh + file nen     hinh_anh/ luu_tru/ video/   noi dung ngau nhien => kho nen
  15%  van phong          tai_lieu/           .docx/.xlsx la file zip that (XML + anh nhung)
  17%  van ban            van_ban/            .txt/.csv/.md tieng Viet => nen tot
   8%  nhieu file nho     cau_hinh/a/b/       .json/.ini/.xml/.txt 512 B - 16 KiB

--mutate X (mo phong 1 ngay lam viec, tat dinh theo --seed va --round):
  chon X% so file (tru file lon): 70% sua, 15% xoa; them file moi = 15% so file da chon;
  file lon bi ghi de ngau nhien X% so byte theo vung 1 MiB (giong trang CSDL bi sua).

Ten file/thu muc tranh cac chuoi con ma bo loc exclude cua v1 se loai nham
(vd "ac", "wer", "tmp") - test tests/test_make_dataset.py kiem tra dieu nay.

Vi du:
  python bench/make_dataset.py --out bench/data/ds --size 500MB --seed 2026
  python bench/make_dataset.py --out bench/data/ds --mutate 5 --round 1 --seed 2026
  python bench/make_dataset.py --out bench/data/ds --digest
"""
import argparse
import hashlib
import io
import json
import math
import os
import random
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.common import fmt_bytes, parse_size, setup_console  # noqa: E402

SEED_DEFAULT = 2026
SIZE_DEFAULT = "500MB"
BIG_REL = "csdl/ban_hang.mdf"
BLOCK = 1024 * 1024
BASE_MTIME = 1767225600          # 2026-01-01 00:00:00 UTC
MUTATE_BASE_MTIME = 1769904000   # 2026-02-01 00:00:00 UTC

FRACTIONS = (("lon", 0.40), ("anh_nen", 0.20), ("van_phong", 0.15),
             ("van_ban", 0.17), ("nho", 0.08))
PHONG_BAN = ["nhan_su", "ke_toan", "kinh_doanh", "ky_thuat", "hanh_chinh", "giam_doc"]
ALBUM = ["su_kien_2025", "san_pham", "nha_may", "hoi_nghi"]
MAY = ["may_tram_01", "may_tram_02", "may_chu_web", "may_in"]
NHOM = ["ung_dung", "dich_vu", "mang", "in_an"]
TEN_DOCX = ["Báo cáo tháng {n:02d}", "Hợp đồng số {n:03d}", "Biên bản họp {n:03d}",
            "Tờ trình {n:03d}", "de_xuat_{n:03d}", "quyet_dinh_{n:03d}"]
TEN_XLSX = ["Bảng lương {n:02d}", "doanh_thu_{n:03d}", "ton_kho_{n:03d}", "bang_gia_{n:03d}"]
TEN_VAN_BAN = ["ghi_chu_{n:04d}.txt", "nhat_ky_{n:04d}.txt", "Thông báo {n:04d}.md",
               "don_hang_{n:04d}.csv", "so_lieu_{n:04d}.csv"]
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".ini", ".xml"}

WORDS = ("công ty khách hàng hợp đồng doanh thu báo cáo kế hoạch nhân viên phòng ban "
         "dự án tiến độ chi phí ngân sách hóa đơn thanh toán sản phẩm dịch vụ kho hàng "
         "giao nhận vận chuyển đối tác cuộc họp quyết định đề xuất phê duyệt hồ sơ tài liệu "
         "mạng máy chủ sao lưu khôi phục bảo mật mật khẩu tài khoản người dùng hệ thống "
         "tháng quý năm tuần ngày số lượng đơn giá tổng cộng tăng giảm so với cùng kỳ "
         "theo yêu cầu của ban giám đốc đề nghị các bộ phận phối hợp thực hiện đúng hạn "
         "và báo cáo kết quả trước ngày cuối tháng nội dung chi tiết xem tại phụ lục kèm theo "
         "trân trọng cảm ơn anh chị đã hỗ trợ trong thời gian qua").split()


# ---------------------------------------------------------------- tien ich

def _rng(*parts):
    """RNG rieng cho tung muc dich -> them/bot 1 file khong lam lech cac file khac."""
    h = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(h[:16], "big"))


def _set_mtime(path, seconds):
    ns = int(seconds) * 1_000_000_000
    os.utime(path, ns=(ns, ns))


def _text(rng, nbytes):
    """Van ban tieng Viet ~nbytes byte (cat theo dong, khong cat giua ky tu UTF-8)."""
    lines, size = [], 0
    while size < nbytes:
        words = rng.choices(WORDS, k=rng.randint(8, 24))
        line = " ".join(words)
        line = line[0].upper() + line[1:] + ".\n"
        lines.append(line)
        size += len(line.encode("utf-8"))
    return "".join(lines).encode("utf-8")


def _csv(rng, nbytes):
    rows, size = ["ma_don,ngay,ma_kh,so_luong,don_gia,thanh_tien\n"], 0
    while size < nbytes:
        qty, price = rng.randint(1, 500), rng.randint(5, 9000) * 1000
        row = (f"DH{rng.randint(1, 10**7):08d},2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d},"
               f"KH{rng.randint(1, 5000):05d},{qty},{price},{qty * price}\n")
        rows.append(row)
        size += len(row)
    return "".join(rows).encode("ascii")


def _records(rng, n):
    """Khoi giong trang du lieu CSDL: ban ghi do dai co dinh 128 byte."""
    out = bytearray()
    while len(out) < n:
        rec = (f"{rng.randint(0, 10**12):012d}|SP{rng.randint(0, 99999):05d}|"
               f"{rng.randint(0, 9999):8d}|{rng.randint(0, 10**9) / 100:14.2f}|"
               f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}|").encode("ascii")
        out += rec.ljust(127, b".") + b"\n"
    return bytes(out[:n])


def _sparse(rng, n):
    """Vung cap phat san cua CSDL: gan nhu toan 0, moi trang 8 KiB co header ngau nhien."""
    buf = bytearray(n)
    for off in range(0, n, 8192):
        hdr = rng.randbytes(min(96, n - off))
        buf[off:off + len(hdr)] = hdr
    return bytes(buf)


def _big_block(rng, n):
    r = rng.random()
    if r < 0.5:
        return rng.randbytes(n)
    if r < 0.8:
        return _records(rng, n)
    return _sparse(rng, n)


def _zip(members):
    """Zip tat dinh: ngay gio co dinh, create_system co dinh."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data, deflate in members:
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
            zi.create_system = 0
            zi.external_attr = 0
            z.writestr(zi, data, compresslevel=6)
    return buf.getvalue()


_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Default Extension="jpeg" ContentType="image/jpeg"/>{over}</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
         'relationships/officeDocument" Target="{target}"/></Relationships>')
_DOC_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>')
_DOC_TAIL = '</w:body></w:document>'
_SHEET_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
_SHEET_TAIL = '</sheetData></worksheet>'
_WORKBOOK = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
_WB_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')


def _paragraphs(rng, raw_bytes):
    parts, size = [], 0
    while size < raw_bytes:
        p = "<w:p><w:r><w:t>" + escape(_text(rng, rng.randint(200, 1200)).decode("utf-8")) + "</w:t></w:r></w:p>"
        parts.append(p)
        size += len(p)
    return parts


def _rows(rng, raw_bytes):
    parts, size = [], 0
    while size < raw_bytes:
        cells = "".join(f"<c><v>{rng.randint(0, 10**7)}</v></c>" for _ in range(6))
        name = escape(" ".join(rng.choices(WORDS, k=3)))
        r = f'<row><c t="inlineStr"><is><t>{name}</t></is></c>{cells}</row>'
        parts.append(r)
        size += len(r)
    return parts


def _office_bytes(ext, rng, target):
    """docx/xlsx toi gian (mo duoc bang Office). ~60% file co anh nhung (kho nen)."""
    media = b""
    if rng.random() < 0.6 and target > 64 * 1024:
        media = b"\xff\xd8\xff\xe0" + rng.randbytes(int(target * rng.uniform(0.3, 0.8)))
    raw_text = max(2048, (target - len(media)) * 3)   # XML nen ~3 lan
    if ext == ".docx":
        main_name, main = "word/document.xml", _DOC_HEAD + "".join(_paragraphs(rng, raw_text)) + _DOC_TAIL
        over = ('<Override PartName="/word/document.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>')
        members = [("[Content_Types].xml", _CT.format(over=over).encode(), True),
                   ("_rels/.rels", _RELS.format(target="word/document.xml").encode(), True),
                   (main_name, main.encode("utf-8"), True)]
        media_name = "word/media/image1.jpeg"
    else:
        main_name, main = "xl/worksheets/sheet1.xml", _SHEET_HEAD + "".join(_rows(rng, raw_text)) + _SHEET_TAIL
        over = ('<Override PartName="/xl/workbook.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        members = [("[Content_Types].xml", _CT.format(over=over).encode(), True),
                   ("_rels/.rels", _RELS.format(target="xl/workbook.xml").encode(), True),
                   ("xl/workbook.xml", _WORKBOOK.encode(), True),
                   ("xl/_rels/workbook.xml.rels", _WB_RELS.encode(), True),
                   (main_name, main.encode("utf-8"), True)]
        media_name = "xl/media/image1.jpeg"
    if media:
        members.append((media_name, media, False))
    return _zip(members)


def _edit_office(path, rng):
    """Sua file van phong nhu nguoi dung: chen vai doan/dong vao phan XML chinh,
    giu nguyen anh nhung (Office ghi lai ca file zip)."""
    with zipfile.ZipFile(path) as z:
        members = [(zi.filename, z.read(zi.filename), zi.compress_type == zipfile.ZIP_DEFLATED)
                   for zi in z.infolist()]
    out = []
    for name, data, deflate in members:
        if name in ("word/document.xml", "xl/worksheets/sheet1.xml"):
            xml = data.decode("utf-8")
            is_doc = name.startswith("word/")
            sep = "</w:p>" if is_doc else "</row>"
            cuts, i = [], xml.find(sep)
            while i != -1:
                cuts.append(i + len(sep))
                i = xml.find(sep, i + 1)
            for _ in range(rng.randint(1, 4)):
                pos = rng.choice(cuts)
                extra = "".join(_paragraphs(rng, 600) if is_doc else _rows(rng, 600))
                xml = xml[:pos] + extra + xml[pos:]
                cuts = [c + len(extra) if c > pos else c for c in cuts]
            data = xml.encode("utf-8")
        out.append((name, data, deflate))
    return _zip(out)


def _media_bytes(ext, rng, n):
    head = {".jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", ".png": b"\x89PNG\r\n\x1a\n",
            ".zip": b"PK\x03\x04", ".mp4": b"\x00\x00\x00\x18ftypmp42"}[ext]
    return head + rng.randbytes(max(0, n - len(head)))


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _sizes(rng, budget, lo, hi):
    """Chia budget thanh cac kich thuoc ngau nhien trong [lo, hi] (file cuoi lay phan con lai).
    Bo du lieu nho thi ha hi de moi nhom van co vai file (500MB khong bi anh huong)."""
    hi = max(lo, min(hi, budget // 4))
    out = []
    while budget > 0:
        n = min(rng.randint(lo, hi), budget)
        if budget - n < lo and budget - n > 0:
            n = budget
        out.append(n)
        budget -= n
    return out


# ---------------------------------------------------------------- sinh du lieu

def generate(out, size=SIZE_DEFAULT, seed=SEED_DEFAULT, verbose=False):
    """Sinh bo du lieu vao thu muc `out` (phai rong hoac chua ton tai). Tra ve tom tat."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Thu muc dich khong rong: {out} (xoa tay hoac chon --out khac)")
    out.mkdir(parents=True, exist_ok=True)
    total = parse_size(size)
    budgets = {cat: int(total * frac) for cat, frac in FRACTIONS}
    clock = [BASE_MTIME]

    def put(rel, data):
        p = out / rel
        _write(p, data)
        clock[0] += 60
        _set_mtime(p, clock[0])

    def log(msg):
        if verbose:
            print(msg, flush=True)

    # 1) File lon (ghi theo khoi, khong giu ca file trong RAM)
    rng = _rng(seed, "lon")
    big = out / BIG_REL
    big.parent.mkdir(parents=True, exist_ok=True)
    with open(big, "wb") as f:
        left = budgets["lon"]
        while left > 0:
            n = min(BLOCK, left)
            f.write(_big_block(rng, n))
            left -= n
    clock[0] += 60
    _set_mtime(big, clock[0])
    log(f"  file lon: {BIG_REL} {fmt_bytes(budgets['lon'])}")

    # 2) Anh / nen / video - kho nen
    rng = _rng(seed, "anh_nen")
    kinds = [(".jpg", 0.6), (".png", 0.15), (".zip", 0.15), (".mp4", 0.10)]
    for i, n in enumerate(_sizes(rng, budgets["anh_nen"], 100 * 1024, 6 * 1024 * 1024), 1):
        ext = ".jpg" if i == 1 else rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
        if ext in (".jpg", ".png"):
            rel = f"hinh_anh/{rng.choice(ALBUM)}/IMG_{i:04d}{ext}"
        elif ext == ".zip":
            rel = f"luu_tru/luu_tru_{i:03d}.zip"
        else:
            rel = f"video/clip_{i:03d}.mp4"
        put(rel, _media_bytes(ext, _rng(seed, rel), n))
    log(f"  anh/nen: {fmt_bytes(budgets['anh_nen'])}")

    # 3) Van phong - docx/xlsx
    rng = _rng(seed, "van_phong")
    for i, n in enumerate(_sizes(rng, budgets["van_phong"], 20 * 1024, 2 * 1024 * 1024), 1):
        ext = ".docx" if i % 2 else ".xlsx"
        tpl = rng.choice(TEN_DOCX if ext == ".docx" else TEN_XLSX)
        rel = f"tai_lieu/{rng.choice(PHONG_BAN)}/{tpl.format(n=i)}{ext}"
        put(rel, _office_bytes(ext, _rng(seed, rel), n))
    log(f"  van phong: {fmt_bytes(budgets['van_phong'])}")

    # 4) Van ban
    rng = _rng(seed, "van_ban")
    for i, n in enumerate(_sizes(rng, budgets["van_ban"], 4 * 1024, 1024 * 1024), 1):
        rel = f"van_ban/{rng.choice(PHONG_BAN)}/{rng.choice(TEN_VAN_BAN).format(n=i)}"
        frng = _rng(seed, rel)
        put(rel, _csv(frng, n) if rel.endswith(".csv") else _text(frng, n))
    log(f"  van ban: {fmt_bytes(budgets['van_ban'])}")

    # 5) Nhieu file nho
    rng = _rng(seed, "nho")
    for i, n in enumerate(_sizes(rng, budgets["nho"], 512, 16 * 1024), 1):
        ext = rng.choice([".json", ".ini", ".xml", ".txt"])
        rel = f"cau_hinh/{rng.choice(MAY)}/{rng.choice(NHOM)}/tham_so_{i:05d}{ext}"
        frng = _rng(seed, rel)
        put(rel, _text(frng, n) if ext == ".txt" else _small_config(ext, frng, n))
    log(f"  file nho: {fmt_bytes(budgets['nho'])}")

    return summary(out)


def _small_config(ext, rng, n):
    if ext == ".json":
        items, size = {}, 2
        while size < n:
            k, v = f"tham_so_{len(items):03d}", rng.randint(0, 10**6)
            items[k] = v
            size += len(k) + 12
        return json.dumps(items, indent=1).encode("ascii")
    if ext == ".ini":
        lines = [f"[muc_{i // 8}]\n" if i % 8 == 0 else f"khoa_{i}={rng.randint(0, 10**6)}\n"
                 for i in range(max(2, n // 16))]
        return "".join(lines).encode("ascii")
    body = "".join(f'<muc id="{i}" gia_tri="{rng.randint(0, 10**6)}"/>' for i in range(max(1, n // 32)))
    return f'<?xml version="1.0" encoding="UTF-8"?><cau_hinh>{body}</cau_hinh>'.encode("ascii")


# ---------------------------------------------------------------- mutate

def iter_files(root):
    """(duong dan tuong doi dang posix, Path) cua moi file, sap xep theo ten."""
    root = Path(root)
    items = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            items.append((p.relative_to(root).as_posix(), p))
    return sorted(items)


def mutate(root, percent, seed=SEED_DEFAULT, round_no=1):
    """Sua/them/xoa ngau nhien (tat dinh) `percent`% file. Tra ve thong ke thay doi."""
    root = Path(root)
    rng = _rng(seed, "mutate", round_no)
    files = [rel for rel, _ in iter_files(root) if rel != BIG_REL]
    if not files:
        raise ValueError(f"Thu muc rong: {root}")
    n = max(1, round(len(files) * percent / 100))
    chosen = rng.sample(files, n)
    n_del = max(1, round(n * 0.15)) if n >= 2 else 0
    n_mod = n - n_del
    n_add = max(1, round(n * 0.15))
    clock = [MUTATE_BASE_MTIME + round_no * 86400]

    def touch(p):
        clock[0] += 1
        _set_mtime(p, clock[0])

    for rel in chosen[:n_mod]:
        p = root / rel
        frng = _rng(seed, "mutate", round_no, rel)
        ext = p.suffix.lower()
        if ext in TEXT_EXT:
            data = p.read_bytes()
            lines = data.split(b"\n")
            pos = frng.randrange(len(lines))
            extra = _text(frng, max(200, len(data) // 20)).rstrip(b"\n")
            lines.insert(pos, extra)
            new = b"\n".join(lines)
        elif ext in (".docx", ".xlsx"):
            new = _edit_office(p, frng)
        else:   # anh/video/zip bi luu lai -> noi dung moi hoan toan
            new = _media_bytes(ext, frng, int(p.stat().st_size * frng.uniform(0.9, 1.1)))
        _write(p, new)
        touch(p)

    for rel in chosen[n_mod:]:
        (root / rel).unlink()

    for j in range(1, n_add + 1):
        frng = _rng(seed, "mutate", round_no, "them", j)
        if frng.random() < 0.5:
            rel = f"van_ban/{frng.choice(PHONG_BAN)}/them_v{round_no}_{j:04d}.txt"
            data = _text(frng, frng.randint(4 * 1024, 256 * 1024))
        else:
            rel = f"tai_lieu/{frng.choice(PHONG_BAN)}/them_v{round_no}_{j:04d}.docx"
            data = _office_bytes(".docx", frng, frng.randint(20 * 1024, 1024 * 1024))
        p = root / rel
        _write(p, data)
        touch(p)

    big_regions = 0
    big = root / BIG_REL
    if big.exists():
        size = big.stat().st_size
        brng = _rng(seed, "mutate", round_no, BIG_REL)
        region = min(BLOCK, size)
        big_regions = max(1, math.ceil(size * percent / 100 / region))
        with open(big, "r+b") as f:
            for _ in range(big_regions):
                off = brng.randrange(0, max(1, size - region + 1)) // 8192 * 8192
                f.seek(off)
                f.write(_big_block(brng, region))
        touch(big)

    return {"chon": n, "sua": n_mod, "xoa": n_del, "them": n_add,
            "vung_file_lon": big_regions}


# ---------------------------------------------------------------- kiem chung

def dataset_digest(root):
    """SHA-256 tren (duong dan, kich thuoc, SHA-256 noi dung) cua moi file, theo thu tu ten."""
    h = hashlib.sha256()
    for rel, p in iter_files(root):
        fh = hashlib.sha256()
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(BLOCK), b""):
                fh.update(block)
        h.update(f"{rel}\0{p.stat().st_size}\0{fh.hexdigest()}\n".encode("utf-8"))
    return h.hexdigest()


def summary(root):
    files = iter_files(root)
    return {"so_file": len(files),
            "tong_byte": sum(p.stat().st_size for _, p in files),
            "digest": dataset_digest(root)}


def main(argv=None):
    setup_console()
    ap = argparse.ArgumentParser(description="Sinh / bien doi bo du lieu mau tat dinh.")
    ap.add_argument("--out", required=True, help="thu muc du lieu")
    ap.add_argument("--size", default=SIZE_DEFAULT, help="tong kich thuoc khi sinh moi (mac dinh 500MB)")
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT)
    ap.add_argument("--mutate", type=float, metavar="PERCENT",
                    help="sua/them/xoa PERCENT%% file trong thu muc da co")
    ap.add_argument("--round", type=int, default=1, help="so vong mutate (doi vong -> thay doi khac)")
    ap.add_argument("--digest", action="store_true", help="chi in tom tat + digest")
    args = ap.parse_args(argv)

    if args.digest:
        result = summary(args.out)
    elif args.mutate is not None:
        result = {"mutate": mutate(args.out, args.mutate, args.seed, args.round), **summary(args.out)}
    else:
        print(f"Sinh du lieu {args.size} (seed={args.seed}) vao {args.out} ...", flush=True)
        result = generate(args.out, args.size, args.seed, verbose=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
