"""Tuan 7: muc nen zstd theo config cua kho + script quet cau hinh chay duoc."""
import csv
import json

from bench import sweep_v2
from core.chunker import ChunkerParams
from core.repo_local import LocalRepo
from core.repository import init_repo
from tests.core_helpers import FAST_SCRYPT, PASSWORD, file_hashes, reopen, write

TEXT = b"dong van ban lap lai de nen tot. " * 4000


def _pack_bytes(kho):
    return sum(p.stat().st_size for p in (kho / "packs").rglob("*") if p.is_file())


def test_muc_nen_ghi_vao_config_va_ap_khi_mo_lai(tmp_path):
    src = tmp_path / "src"
    write(src / "a.txt", TEXT)
    sizes = {}
    for lvl in (0, 9):
        kho = tmp_path / f"kho{lvl}"
        repo = init_repo(LocalRepo(kho), PASSWORD, ChunkerParams(), scrypt=FAST_SCRYPT, zstd_level=lvl)
        assert json.loads((kho / "config").read_bytes())["compression"]["level"] == lvl
        again = reopen(kho)
        assert again.keys.compress is (lvl > 0)
        again.backup([str(src)])
        sizes[lvl] = _pack_bytes(kho)
        out = tmp_path / f"out{lvl}"
        again.restore(again.resolve("latest"), out)
        assert file_hashes(out / "src") == file_hashes(src)
    assert sizes[0] > len(TEXT)          # khong nen: pack >= du lieu goc
    assert sizes[9] < len(TEXT) // 10    # nen: nho hon han


def test_sweep_chay_va_ghi_csv(tmp_path, capsys):
    out_csv = tmp_path / "sweep.csv"
    sweep_v2.main(["--size", "3MB", "--avg", "256,512", "--levels", "0,3",
                   "--workdir", str(tmp_path / "w"), "--csv", str(out_csv)])
    with open(out_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 * 2 * 3
    assert {r["phien_ban"] for r in rows} == {f"v2 avg={a}K zstd={z}" for a in (256, 512) for z in (0, 3)}
    for r in rows:
        assert int(r["byte_gui"]) > 0 and int(r["dung_luong_kho"]) > 0
    assert "to hop" in capsys.readouterr().out


def test_restic_khong_co_thi_dung_va_khong_ghi_gi(tmp_path, capsys):
    from bench import bench_restic
    rc = bench_restic.main(["--restic", str(tmp_path / "khong_co" / "restic.exe"),
                            "--workdir", str(tmp_path / "w"), "--csv", str(tmp_path / "r.csv")])
    assert rc == 3
    assert not (tmp_path / "w").exists() and not (tmp_path / "r.csv").exists()
    assert "Khong tim thay restic" in capsys.readouterr().out


def test_restic_doc_summary_json():
    from bench.bench_restic import parse_summary, sent_bytes
    out = "\n".join([
        '{"message_type":"status","percent_done":0.5}',
        "dong rac khong phai json",
        '{"message_type":"summary","files_new":3,"data_added":1000,"data_added_packed":400,'
        '"total_files_processed":3,"total_bytes_processed":5000,"snapshot_id":"abc"}',
    ])
    s = parse_summary(out)
    assert sent_bytes(s) == (400, "data_added_packed")
    assert sent_bytes({"data_added": 7}) == (7, "data_added")
