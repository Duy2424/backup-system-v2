"""Logging thong nhat: console + file xoay vong trong work/logs/."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def setup_logging(name, logs_dir=None, level=logging.INFO):
    """Goi 1 lan o entry point (server/agent). Tra ve logger goc cua ung dung."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(h, "_backup_system", False) for h in root.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter(_FMT, "%H:%M:%S"))
        console._backup_system = True
        root.addHandler(console)
        if logs_dir:
            os.makedirs(logs_dir, exist_ok=True)
            fh = RotatingFileHandler(os.path.join(logs_dir, f"{name}.log"),
                                     maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
            fh.setFormatter(logging.Formatter(_FMT))
            fh._backup_system = True
            root.addHandler(fh)
    # Bot log moi request cua werkzeug/waitress (UI poll lien tuc)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return logging.getLogger(name)
