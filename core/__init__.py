"""
Loi v2: chia mau (FastCDC) + khu trung lap + ma hoa AES-256-GCM, kho chi cho them.
Dinh dang kho: docs/repo-format.md (hop dong giua Nguoi A va Nguoi B).

  scanner     duyet thu muc, metadata, cache theo (path, size, mtime) tu snapshot truoc
  chunker     FastCDC dang stream
  crypto      khoa (scrypt), chunk ID = HMAC-SHA256, ma hoa mau AES-GCM
  packer      gom mau thanh pack, index ma hoa, xac minh
  repo_local  backend kho tren thu muc (test + offline), cung giao dien voi client HTTP tuan 3
  repository  init / backup / restore / snapshots / check
  cli         python -m core ...
"""
FORMAT_VERSION = 1
