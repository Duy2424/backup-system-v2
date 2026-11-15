"""
Chay API kho v2:  python -m kho --kho D:\\kho-v2 [--host 127.0.0.1] [--port 8080]

Mac dinh chi nghe 127.0.0.1: Caddy (deploy/kho/Caddyfile) dung truoc, lo TLS + mTLS, roi chuyen vao day.
Bien moi truong thay cho tham so: KHO_DIR, KHO_HOST, KHO_PORT.
"""
import argparse
import logging
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.repo_local import MAX_SNAPSHOT  # noqa: E402
from kho.app import VERSION, create_app  # noqa: E402
from shared.log import setup_logging  # noqa: E402

log = logging.getLogger("kho")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kho", description="API kho v2 - chỉ thêm, không xoá (chạy sau Caddy mTLS)")
    ap.add_argument("--kho", default=os.environ.get("KHO_DIR", ""), help="thư mục kho (hoặc biến KHO_DIR)")
    ap.add_argument("--host", default=os.environ.get("KHO_HOST", "127.0.0.1"),
                    help="mặc định 127.0.0.1: chỉ Caddy cùng máy gọi vào được")
    ap.add_argument("--port", type=int, default=int(os.environ.get("KHO_PORT", "8080")))
    ap.add_argument("--log-dir", default=None, help="mặc định <kho>\\logs")
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args(argv)
    if not args.kho:
        ap.error("cần --kho <thư mục> hoặc biến môi trường KHO_DIR")
    kho = os.path.abspath(args.kho)
    os.makedirs(kho, exist_ok=True)
    setup_logging("kho", args.log_dir or os.path.join(kho, "logs"))

    app = create_app(kho)
    repo = app.config["kho_repo"]
    idx = repo._load_index()                         # dung lai index tu footer + bang ID (pack ghi xong luc sap)
    log.info("KHO v2 %s - thư mục %s: %d pack, %s mẩu, %d snapshot, %s",
             VERSION, kho, len(repo.list_packs()), f"{len(idx):,}", len(repo.list_snapshots()),
             "đã init" if repo.exists() else "CHƯA init (chạy: python -m core init --repo http://...)")
    log.info("Nghe http://%s:%s - KHÔNG có lệnh xoá. Dừng: Ctrl+C", args.host, args.port)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Đang nghe %s (không chỉ loopback): chỉ làm vậy khi mạng đã được bảo vệ (Tailscale/firewall)", args.host)
    try:
        from waitress import serve
    except ImportError:
        log.warning("Chưa cài waitress - dùng server thử nghiệm của Flask")
        app.run(host=args.host, port=args.port, threaded=True)
        return 0
    serve(app, host=args.host, port=args.port, threads=args.threads, max_request_body_size=MAX_SNAPSHOT + 2 * 1024 * 1024,
          channel_timeout=300, ident="backup-kho")
    return 0


if __name__ == "__main__":
    sys.exit(main())
