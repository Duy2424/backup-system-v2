# Định dạng kho v2 (repo-format) — hợp đồng giữa Người A và Người B

> Phiên bản định dạng: **1** · Trạng thái: **BẢN NHÁP chờ B chốt** · Cập nhật: 2026-10-14
>
> Người A (lõi dữ liệu) viết client: cắt mẩu, mã hoá, gom pack, snapshot (`core/`).
> Người B (mạng/vận hành) viết **API kho** chạy trên PC, đứng sau Caddy mTLS.
> Mọi thay đổi định dạng phải sửa file này trước, tăng `version`, hai bên cùng đồng ý.

Các mục đánh dấu **[CẦN B CHỐT]** là chỗ A đề xuất nhưng B phải đồng ý trước khi code.

---

## 0. Tóm tắt một trang

```
 máy agent (A)                                              kho trên PC (B)
 ──────────────                                             ───────────────
 file ─► FastCDC ─► chunk ─► ID = HMAC-SHA256(id_key, chunk)
                               │
                               ├─ POST /chunks/missing [ID…] ──────────────► "thiếu những ID nào?"
                               │◄──────────────────────────── [ID thiếu]
                               ▼
              chỉ mẩu thiếu: zstd ─► AES-256-GCM(enc_key, AAD = ID)
                               ▼
              gom ~16 MiB ─► pack (index mã hoá + bảng ID) ─ PUT /packs/<sha256> ─► ghi tạm → đổi tên
                               ▼
              SAU CÙNG: snapshot (JSON mã hoá)  ─────────── PUT /snapshots/<sha256> ─►
```

- Kho **chỉ thấy**: chunk ID (HMAC, không suy ra được nội dung), kích thước pack/snapshot, số mẩu trong mỗi pack. Không thấy tên file, nội dung, cấu trúc thư mục.
- Kho **chỉ cho thêm**: không có lệnh xoá, không ghi đè, PUT trùng id = bỏ qua (idempotent).
- Bất biến quan trọng nhất: **snapshot tồn tại ⇒ mọi mẩu nó tham chiếu đã nằm trong pack đã ghi xong** (vì pack ghi trước, snapshot ghi sau cùng).

---

## 1. Thuật ngữ

| Từ | Nghĩa |
|---|---|
| chunk / mẩu | Một đoạn byte liên tiếp của file, ranh giới do FastCDC chọn theo nội dung |
| chunk ID | `HMAC-SHA256(id_key, plaintext_chunk)`, 32 byte, viết hex thường 64 ký tự |
| blob | Mẩu đã nén (tuỳ chọn) + mã hoá: `nonce ‖ ciphertext ‖ tag` |
| pack | File gom nhiều blob (~16 MiB) + index mã hoá + bảng ID + footer |
| pack ID | `SHA-256(toàn bộ byte của pack)`, hex 64 ký tự |
| snapshot | Bản ghi một lần backup: thời gian, máy, cây file → danh sách chunk ID; được mã hoá |
| snapshot ID | `SHA-256(toàn bộ byte của file snapshot)`, hex 64 ký tự |
| `enc_key` | Khoá AES-256 (32 byte) mã hoá blob, index, snapshot |
| `id_key` | Khoá HMAC (32 byte) tính chunk ID. **Khác** `enc_key` |
| key file | File JSON chứa `enc_key` + `id_key` đã được bọc bằng mật khẩu (scrypt) |

Mọi số nguyên nhị phân là **little-endian**. Mọi JSON là UTF-8, không BOM. Mọi ID dạng hex dùng **chữ thường**.

---

## 2. Cắt mẩu (chunking)

- Thuật toán: **FastCDC** (Xia et al., USENIX ATC 2016) có chuẩn hoá (normalized chunking) mức 1, dùng cài đặt
  `fastcdc==1.7.0` (bản Cython `fastcdc_cy`). Ranh giới mẩu phụ thuộc chi tiết cài đặt nên **pin đúng version**;
  đổi thư viện = đổi `chunker.algorithm` trong `config` (dedup giữa bản cũ/mới giảm, nhưng dữ liệu vẫn đúng).
- Tham số mặc định (cấu hình được trong `config`, mọi client của cùng một kho phải dùng cùng tham số để dedup với nhau):

  | Tham số | Mặc định | Byte |
  |---|---|---|
  | `min_size` | 512 KiB | 524 288 |
  | `avg_size` | 1 MiB | 1 048 576 |
  | `max_size` | 8 MiB | 8 388 608 |

- File nhỏ hơn `min_size` thành đúng 1 mẩu. **File rỗng có 0 mẩu** (danh sách chunk rỗng).
- Cắt kiểu streaming: client đọc file theo khối, không nạp cả file vào RAM. Ranh giới mẩu chỉ phụ thuộc
  tối đa `max_size` byte kể từ đầu mẩu nên kết quả giống hệt cắt cả file một lần.

## 3. Chunk ID

```
chunk_id = HMAC-SHA256(key = id_key, msg = plaintext_chunk)      # 32 byte
```

Dùng khoá riêng (`id_key`) thay vì SHA-256 thuần: người giữ kho không thể "đoán thử" một file
đã biết (vd mẫu hợp đồng) rồi tính hash để biết công ty có file đó hay không.
Hai mẩu giống hệt nhau trong cùng một kho luôn có cùng ID ⇒ chỉ lưu một lần (dedup).

## 4. Mã hoá một mẩu (blob)

```
payload    = type (1 byte) ‖ data
             type 0x00: data = plaintext
             type 0x01: data = zstd(plaintext, level 3)       # chỉ dùng khi nén làm NHỎ hơn
nonce      = 12 byte ngẫu nhiên (os.urandom)
ct ‖ tag   = AES-256-GCM(key = enc_key, nonce, payload, AAD = chunk_id (32 byte thô))
blob       = nonce (12) ‖ ct (len(payload)) ‖ tag (16)
```

- AAD = chunk ID gắn chặt blob với ID của nó: tráo blob giữa hai ID ⇒ giải mã báo lỗi xác thực.
- Sau khi giải mã, client **tính lại** `HMAC(id_key, plaintext)` và so với chunk ID (kiểm tra kép).
- Byte `type` nằm **bên trong** phần mã hoá (kho không biết mẩu nào nén được).
- Nonce ngẫu nhiên 96 bit: giới hạn an toàn ~2³² lần mã hoá với một khoá ≈ 4 PiB ở mẩu 1 MiB — dư cho đồ án.

## 5. Khoá

### 5.1 Khoá chủ

Sinh **một lần** khi `init`: `enc_key = urandom(32)`, `id_key = urandom(32)`. Không bao giờ ghi ra đĩa ở dạng rõ.

### 5.2 Key file `keys/<key_id>`

```json
{
  "version": 1,
  "created": "2026-10-14T10:00:00+07:00",
  "host": "LAPTOP-DUY",
  "user": "duy",
  "kdf":  { "name": "scrypt", "n": 32768, "r": 8, "p": 1, "salt": "3q2+7w0B...base64 16 byte..." },
  "wrap": { "cipher": "AES-256-GCM", "nonce": "base64 12 byte", "data": "base64(ciphertext ‖ tag)" }
}
```

- `kek = scrypt(password_utf8, salt, n, r, p, dklen = 32)` (~32 MiB RAM, ~0,1–0,3 s).
- `wrap.data = AES-256-GCM(kek, nonce, plaintext, AAD = b"BSV2KEY\x01")`, với plaintext là JSON
  `{"repo_id": "<repo_id>", "enc_key": "<base64>", "id_key": "<base64>"}`.
- Sai mật khẩu ⇒ GCM báo lỗi xác thực ⇒ không mở được kho (không có "gần đúng").
- `key_id = SHA-256(byte của key file)` hex. Có thể có **nhiều** key file (nhiều mật khẩu) cùng bọc một khoá chủ.
- **Mất mật khẩu = mất dữ liệu.** Hướng dẫn vận hành: in mật khẩu + bản sao key file cất két (B ghi vào runbook).

## 6. Pack `packs/<2 ký tự đầu>/<pack_id>`

### 6.1 Bố cục nhị phân

| Vị trí | Độ dài | Nội dung |
|---|---|---|
| 0 | 8 | Header: `"BSV2PK"` + version `0x01` + `0x00` |
| 8 | Σ len(blobᵢ) | `blob₁ ‖ blob₂ ‖ … ‖ blobₙ` (nối liền, không có tiền tố độ dài) |
| … | L = 28 + 48·n | **Index mã hoá**: `nonce(12) ‖ AES-256-GCM(enc_key, nonce, index_plain, AAD) ‖ tag(16)` |
| … | 32·n | **Bảng ID** (rõ): n chunk ID thô, cùng thứ tự với blob |
| cuối − 16 | 16 | Footer: `L` (u32) ‖ `n` (u32) ‖ `"BSV2PEND"` |

- `index_plain` = n bản ghi 48 byte, mỗi bản ghi `struct "<32sQII"`:
  `chunk_id (32) ‖ offset (u64, tính từ đầu pack) ‖ length (u32, độ dài blob) ‖ raw_length (u32, độ dài plaintext)`.
- `AAD` của index = `b"BSV2IDX\x01" ‖ bảng ID`. Như vậy bảng ID rõ cũng được xác thực: kho sửa bảng ID
  thì client giải mã index sẽ báo lỗi.
- `pack_id = SHA-256(toàn bộ pack)` ⇒ cả kho lẫn client kiểm tra lại được tên ↔ nội dung.
- Kích thước mục tiêu 16 MiB (`pack_target_size` trong config): client đóng pack khi thêm blob tiếp theo
  sẽ vượt mục tiêu. Pack lớn nhất ≈ 16 MiB + index + bảng ID < **64 MiB** (giới hạn kho chấp nhận).

### 6.2 Vì sao có bảng ID rõ?

Kho phải trả lời `/chunks/missing` mà **không có khoá**. Bảng ID cho kho biết pack chứa những ID nào.
ID là HMAC có khoá nên không lộ nội dung; offset/độ dài từng blob vẫn nằm trong index đã mã hoá.

### 6.3 Kho kiểm tra gì khi nhận pack (không cần khoá)

1. `SHA-256(body) == pack_id` trong URL.
2. Header bắt đầu bằng `BSV2PK\x01`, footer kết thúc bằng `BSV2PEND`.
3. `1 ≤ n ≤ 1 048 576`, `L == 28 + 48·n`, `8 + L + 32·n + 16 ≤ size`, vùng blob ≥ `30·n` byte (blob nhỏ nhất = 12 + 2 + 16).
4. Kích thước ≤ 64 MiB.

Đạt hết ⇒ đọc bảng ID để cập nhật index phía kho.

## 7. Snapshot `snapshots/<snapshot_id>`

### 7.1 Bố cục

| Vị trí | Độ dài | Nội dung |
|---|---|---|
| 0 | 8 | Header `"BSV2SN"` + version `0x01` + `0x00` |
| 8 | 12 | nonce |
| 20 | … | `AES-256-GCM(enc_key, nonce, zstd(JSON), AAD = header 8 byte)` ‖ tag |

`snapshot_id = SHA-256(toàn bộ file)`. Kho chỉ thấy kích thước.

### 7.2 Nội dung JSON (sau giải mã)

```json
{
  "version": 1,
  "time": "2026-10-14T21:30:05+07:00",
  "host": "LAPTOP-DUY",
  "user": "duy",
  "roots": [ { "name": "du_lieu", "source": "D:\\Data\\du_lieu" } ],
  "parent": "6c1f…(snapshot ID lần trước, hoặc null)",
  "tags": ["hang-ngay"],
  "chunker": { "algorithm": "fastcdc-1.7.0", "min_size": 524288, "avg_size": 1048576, "max_size": 8388608 },
  "stats": {
    "files": 5321, "dirs": 87, "bytes": 524288000,
    "chunks": 812, "chunks_new": 41, "bytes_new": 39845888,
    "packs_new": 3, "bytes_uploaded": 31457280, "seconds": 18.4
  },
  "tree": [
    { "path": "du_lieu/tai_lieu", "type": "dir", "mtime_ns": 1767225600000000000, "attrs": 16 },
    { "path": "du_lieu/tai_lieu/Báo cáo tháng 01.docx", "type": "file",
      "size": 183442, "mtime_ns": 1767225660000000000, "attrs": 32,
      "chunks": ["9f2c…64 hex", "0a7e…64 hex"] },
    { "path": "du_lieu/rong.txt", "type": "file", "size": 0, "mtime_ns": 1767225720000000000,
      "attrs": 32, "chunks": [] }
  ]
}
```

- `path`: luôn dùng `/`, bắt đầu bằng `roots[i].name`; trùng tên gốc thì client thêm hậu tố `~2`, `~3`.
- `attrs`: thuộc tính file Windows (`st_file_attributes`), để khôi phục ReadOnly/Hidden.
- `tree` có cả thư mục (kể cả thư mục rỗng) để khôi phục đúng cây.
- Thứ tự `chunks` = thứ tự byte trong file. Nối plaintext các mẩu = nội dung file.

## 8. File `config` (rõ, không bí mật)

```json
{
  "format": "backup-system-v2",
  "version": 1,
  "repo_id": "5f0c9e2b7a1d4c3e8f6a0b1c2d3e4f50",
  "created": "2026-10-14T10:00:00+07:00",
  "chunker": { "algorithm": "fastcdc-1.7.0", "min_size": 524288, "avg_size": 1048576, "max_size": 8388608 },
  "pack_target_size": 16777216,
  "compression": { "algorithm": "zstd", "level": 3 },
  "cipher": "AES-256-GCM",
  "chunk_id": "HMAC-SHA256",
  "kdf": "scrypt"
}
```

Client gặp `version` lớn hơn bản mình hiểu ⇒ từ chối làm việc với kho (không đoán).

## 9. Bố cục thư mục kho

```
<thư mục kho>\                       (vd D:\kho-backup trên PC)
├── config                           ghi 1 lần khi init
├── keys\
│   └── <key_id>                     ghi 1 lần mỗi key file
├── packs\
│   ├── 00\ … ff\                    256 thư mục con theo 2 ký tự hex đầu của pack_id
│   │   └── <pack_id>                64 hex, không đuôi
├── snapshots\
│   └── <snapshot_id>                64 hex, không đuôi
├── tmp\                             (nội bộ kho) file đang nhận, CÙNG ổ đĩa để đổi tên nguyên tử
└── index\                           (nội bộ kho) chunk_id → pack_id; dựng lại được từ packs\
```

- `tmp\` và `index\` là chi tiết riêng của B; client không đọc trực tiếp. Backend kho cục bộ của A
  (`core/repo_local.py`) dựng index trong RAM bằng cách đọc footer + bảng ID của mọi pack.
- Quyền NTFS (việc của B): tài khoản chạy API kho được tạo/ghi file nhưng **bị deny Delete** trên `packs\`,
  `snapshots\`, `keys\`, `config`.

## 10. API kho

Mọi đường dẫn tương đối với `BASE` (vd `https://pc-kho.<tailnet>.ts.net:8443`).
Caddy (B) kết thúc TLS và **bắt buộc chứng chỉ client** (mTLS); app kho chỉ nghe `127.0.0.1`.
Không có cookie/token riêng: ai qua được mTLS là client hợp lệ. **[CẦN B CHỐT]** Caddy có chuyển
subject chứng chỉ vào header `X-Client-Subject` để kho ghi log không.

Định dạng lỗi chung (mọi mã ≥ 400):

```json
{ "error": "hash_mismatch", "detail": "sha256(body)=ab12… khác id trong URL" }
```

### 10.1 Bốn lệnh chính (bắt buộc, tuần 2–3)

#### (1) `POST /chunks/missing` — hỏi kho thiếu mẩu nào

Request (`Content-Type: application/json`, tối đa **10 000** ID/lần; client mặc định gửi lô 1 000):

```json
{ "ids": ["9f2c…", "0a7e…", "77d1…"] }
```

Response `200`:

```json
{ "missing": ["0a7e…"] }
```

- `missing` giữ thứ tự xuất hiện trong request, bỏ trùng.
- Một ID được coi là **có** chỉ khi pack chứa nó đã ghi xong (đã đổi tên từ `tmp\` vào `packs\`).

| Mã | `error` | Khi nào |
|---|---|---|
| 200 | — | OK |
| 400 | `bad_request` | JSON hỏng, thiếu `ids`, ID không phải 64 hex thường |
| 413 | `too_many_ids` | > 10 000 ID |

#### (2) `PUT /packs/<pack_id>` — gửi pack

Request: `Content-Type: application/octet-stream`, **bắt buộc `Content-Length`**, body = byte của pack.

Kho làm theo thứ tự:
1. Nếu `packs\<ab>\<pack_id>` đã có ⇒ trả `200 {"status": "exists"}` (không ghi, không đổi gì).
2. Ghi stream vào `tmp\<ngẫu nhiên>`, vừa ghi vừa tính SHA-256, rồi `fsync`.
3. Kiểm tra theo §6.3. Sai ⇒ xoá file tạm, trả lỗi.
4. **Đổi tên nguyên tử** `tmp\…` → `packs\<ab>\<pack_id>` (Windows `MoveFileEx` không có cờ REPLACE ⇒
   nếu đích đã tồn tại do upload song song thì báo lỗi, coi như `exists`).
5. Cập nhật index (chunk_id → pack_id) **sau** khi đổi tên. Kho sập giữa bước 4 và 5 ⇒ lúc khởi động
   lại kho phải quét pack chưa có trong index và bổ sung.

| Mã | `error` / `status` | Khi nào |
|---|---|---|
| 201 | `{"status":"created","chunks":n}` | Ghi mới thành công |
| 200 | `{"status":"exists"}` | Pack đã có (PUT lặp lại là vô hại) |
| 400 | `bad_id` | `pack_id` không phải 64 hex thường |
| 400 | `hash_mismatch` | SHA-256 body ≠ `pack_id` |
| 400 | `bad_pack` | Sai header/footer/kích thước theo §6.3 |
| 411 | `length_required` | Thiếu `Content-Length` |
| 413 | `too_large` | > 64 MiB |
| 507 | `insufficient_storage` | Đĩa kho đầy |

#### (3) `GET /packs/<pack_id>` — tải pack

- `200` + body nguyên vẹn, `Content-Type: application/octet-stream`, `ETag: "<pack_id>"`.
- **Nên hỗ trợ `Range: bytes=a-b` ⇒ `206`** (tuần 4: khôi phục 1 file chỉ tải đúng các blob cần).
- `404 not_found` nếu không có; `416 range_not_satisfiable` nếu Range sai.

#### (4) `PUT /snapshots/<snapshot_id>` — ghi snapshot (luôn là bước CUỐI)

- Body = file snapshot (≤ 256 MiB). Kho kiểm tra `SHA-256(body) == snapshot_id` và header `BSV2SN\x01`,
  ghi tạm → đổi tên như pack.
- Mã: `201 created`, `200 exists`, `400 bad_id | hash_mismatch | bad_snapshot`, `411`, `413`, `507`.
- Kho **không** kiểm tra được snapshot tham chiếu mẩu nào (đã mã hoá) ⇒ bất biến "snapshot ⇒ đủ mẩu"
  do **client** đảm bảo bằng thứ tự ghi (§11).

### 10.2 Lệnh đọc bổ sung cho restore/init — **[CẦN B CHỐT]**

Chỉ với 4 lệnh trên thì backup được nhưng **không khôi phục được qua mạng**: client không liệt kê/tải được
snapshot, không biết mẩu nằm ở pack nào, máy mới không lấy được `config`/key file. A đề xuất thêm các lệnh
**chỉ đọc hoặc ghi-một-lần** sau (vẫn không có xoá):

| Lệnh | Request | Response | Ghi chú |
|---|---|---|---|
| `GET /snapshots` | — | `{"snapshots":[{"id":"…","size":1234,"mtime":"2026-10-14T21:30:06+07:00"}]}` | Danh sách để chọn bản khôi phục |
| `GET /snapshots/<id>` | — | byte file snapshot | `404` nếu không có |
| `POST /chunks/locate` | `{"ids":[…]}` (≤ 10 000) | `{"locations":{"<chunk_id>":"<pack_id>"},"missing":[…]}` | Biết mẩu ở pack nào để tải |
| `GET /config` | — | byte file `config` | |
| `PUT /config` | byte `config` | `201` / `200` nếu giống hệt / `409 conflict` nếu khác | Ghi một lần khi `init` |
| `GET /keys` | — | `{"keys":["<key_id>",…]}` | |
| `GET /keys/<key_id>` | — | byte key file | |
| `PUT /keys/<key_id>` | byte key file | `201` / `200` / `400 hash_mismatch` | Ghi một lần; `key_id = SHA-256(body)` |

### 10.3 Quy tắc chung

- **Không có DELETE** ở bất kỳ đâu. Mọi method/đường dẫn khác ⇒ `405 method_not_allowed` / `404`.
- Không lệnh nào ghi đè file đã có. Mọi PUT đều idempotent theo id = SHA-256 nội dung.
- Client thử lại (backoff 1, 2, 4, 8, 16, 32 s, tối đa 6 lần) khi lỗi mạng hoặc mã `429/500/502/503/504`;
  **không** thử lại với 4xx khác.
- Timeout gợi ý: kết nối 10 s, đọc/ghi 120 s cho mỗi pack.

## 11. Thứ tự ghi và chạy lại sau sự cố

```
1. quét + cắt mẩu → danh sách chunk ID của mọi file
2. POST /chunks/missing theo lô
3. chỉ với mẩu thiếu: mã hoá → gom pack → PUT /packs/<id>      (lặp)
4. đợi MỌI pack trả 200/201
5. PUT /snapshots/<id>                                           ← sau cùng
```

- Đứt mạng ở bước 3: lần chạy sau làm lại từ bước 1. Mẩu thuộc pack **đã ghi xong** không còn trong
  `missing` ⇒ không gửi lại. Pack đang gửi dở chỉ nằm trong `tmp\` của kho, không được tính.
- Hai máy cùng gửi một mẩu cùng lúc ⇒ mẩu có thể nằm ở 2 pack. Vô hại (tốn chút chỗ), index chọn pack nào cũng được.

## 12. Kiểm tra toàn vẹn (`check`)

| Ai | Không cần khoá | Cần khoá (client) |
|---|---|---|
| Pack | SHA-256 = tên; header/footer đúng §6.3 | Giải mã index (xác thực cả bảng ID); giải mã từng blob (GCM) và so lại HMAC |
| Snapshot | SHA-256 = tên; header đúng | Giải mã; mọi chunk ID trong `tree` phải có trong index |
| Kho | `config` đọc được, `keys\` có ≥ 1 file | Mở được bằng mật khẩu |

Sửa **bất kỳ 1 byte** nào trong pack ⇒ hoặc SHA-256 sai tên, hoặc GCM báo lỗi ⇒ client từ chối, không
bao giờ trả dữ liệu sai.

## 13. Ngoài phạm vi API (ghi để không quên)

- **Dọn bản hết hạn (tuần 5)** cần xoá pack/snapshot — mâu thuẫn với append-only nếu đi qua API.
  Đề xuất: dọn chạy **cục bộ trên PC** bằng tài khoản quản trị riêng (không phải tài khoản chạy API),
  trong khung giờ bảo trì; API vẫn không có lệnh xoá. **[CẦN B CHỐT]**
- Bản sao lên cloud Object Lock (tuần 5, B): rclone đồng bộ nguyên thư mục kho; định dạng không đổi.

## 14. Việc B cần xác nhận

- [ ] Đường dẫn + mã lỗi của 4 lệnh chính (§10.1)
- [ ] Các lệnh đọc bổ sung (§10.2) — nếu không đồng ý thì restore qua mạng phải làm cách khác
- [ ] Giới hạn: 10 000 ID/lần, pack ≤ 64 MiB, snapshot ≤ 256 MiB
- [ ] Ghi tạm → đổi tên trên cùng ổ, index cập nhật sau đổi tên, tự quét bổ sung khi khởi động
- [ ] Header `X-Client-Subject` từ Caddy (tuỳ chọn)
- [ ] Cách dọn bản hết hạn (§13)
