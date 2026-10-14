#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resolve_conflicts.py
--------------------------------------------------------------------
Go (resolve) toan bo merge conflict con sot trong repo, GIU LAI nhanh HEAD
va xoa nhanh c150db19... (nhanh sai theo bao cao).

Cach dung:
    1. Chep file nay vao THU MUC GOC cua repo (cung cap voi server/, agent/).
    2. Chay:   python resolve_conflicts.py
    3. Script se quet tat ca file .py .html .txt .bat .md .gitignore,
       file nao con dau <<<<<<< ======= >>>>>>> thi giu phan HEAD, bo phan kia.

An toan: file nao KHONG co dau xung dot se duoc bo qua (khong sua).
Script tu dong bo qua thu muc .git, work, storage, __pycache__.
--------------------------------------------------------------------
"""
import os
import sys

# Phan mo rong file se duoc xu ly
EXTS = {".py", ".html", ".htm", ".txt", ".bat", ".md", ".css", ".js", ".json"}
EXTRA_NAMES = {".gitignore"}            # file khong co duoi
SKIP_DIRS = {".git", "work", "storage", "__pycache__", ".venv", "venv", "node_modules"}


def resolve_text(text):
    """
    Tra ve (noi_dung_da_go, so_xung_dot_da_xu_ly).
    Quy tac: giu cac dong tu sau '<<<<<<<' den truoc '=======',
             bo cac dong tu '=======' den '>>>>>>>' (ke ca 3 dong dau).
    """
    out = []
    state = "normal"      # normal | head | other
    conflicts = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if state == "normal":
            if stripped.startswith("<<<<<<<"):
                state = "head"
                conflicts += 1
                continue          # bo dong dau <<<<<<<
            out.append(line)
        elif state == "head":
            if stripped.startswith("======="):
                state = "other"   # bat dau phan c150db19 -> bo
                continue
            if stripped.startswith(">>>>>>>"):
                # truong hop hiem: khong co ======= -> ket thuc luon
                state = "normal"
                continue
            out.append(line)     # giu phan HEAD
        elif state == "other":
            if stripped.startswith(">>>>>>>"):
                state = "normal"  # het khoi xung dot
                continue
            # bo cac dong cua nhanh kia
            continue
    return "".join(out), conflicts


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    total_files = 0
    total_conflicts = 0
    changed = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            _, ext = os.path.splitext(name)
            if ext.lower() not in EXTS and name not in EXTRA_NAMES:
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            if "<<<<<<<" not in text:
                continue
            new_text, n = resolve_text(text)
            if n > 0 and new_text != text:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
                rel = os.path.relpath(path, root)
                changed.append((rel, n))
                total_files += 1
                total_conflicts += n

    print("=" * 60)
    if changed:
        print("DA GO XUNG DOT (giu HEAD) trong cac file:")
        for rel, n in changed:
            print("  - %-45s (%d khoi)" % (rel, n))
        print("-" * 60)
        print("Tong: %d file, %d khoi xung dot da xu ly." % (total_files, total_conflicts))
    else:
        print("Khong tim thay xung dot nao (repo da sach).")
    print("=" * 60)
    print("Buoc tiep theo: chep de cac file sach trong thu muc nay vao repo,")
    print("roi chay:  pip install -r requirements.txt")


if __name__ == "__main__":
    main()
