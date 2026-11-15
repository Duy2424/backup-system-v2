"""
Thong bao (tuan 6, B): moi su kien dang chu y duoc ghi vao bang `events` (web hien o muc Thong bao) va, neu da
cau hinh bot Telegram, gui tin kem 2 nut **Binh thuong** / **Su co** de quan tri bam xac nhan ngay tren dien thoai.

- Token / chat id: nhap o web (Cai dat > Telegram, luu bang settings) hoac bien BACKUP_TELEGRAM_TOKEN / _CHAT_ID.
- Gui tin chay o thread rieng (khong lam cham request). Loi mang chi ghi log.
- TelegramPoller: long-poll getUpdates; bam nut -> ack su kien + sua tin (bo nut, ghi "Da xac nhan: ... boi ...");
  nhan /start hoac /id -> tra loi chat id (de dan vao Cai dat). Khong tu dong gan chat id (ai cung co the nhan bot).
"""
import html
import logging
import re
import threading
from datetime import datetime

import requests

from shared import config, database
from shared.text import vn_int, vn_mb, vn_num

log = logging.getLogger("notify")
API = "https://api.telegram.org/bot{token}/{method}"
ICON = {"ok": "✅", "info": "ℹ️", "warn": "⚠️", "err": "❌"}
ACK_TEXT = {"binh_thuong": "Bình thường", "su_co": "Sự cố"}
SYNC = False            # test: gui dong bo
LAST_ERROR = ""         # loi gui gan nhat (hien o nut "Gui tin thu")


def settings():
    """Cau hinh Telegram: web (bang settings) > bien moi truong."""
    s = database.all_settings("telegram_")
    return {"token": s.get("telegram_token") or config.TELEGRAM_TOKEN or "",
            "chat_id": s.get("telegram_chat_id") or config.TELEGRAM_CHAT_ID or "",
            "enabled": s.get("telegram_enabled", "1") == "1",
            "notify_ok": s.get("telegram_notify_ok", "1") == "1"}


def telegram(method, token, http_timeout=15, **params):
    r = requests.post(API.format(token=token, method=method), json=params, timeout=http_timeout)
    try:
        d = r.json()
    except ValueError:
        raise RuntimeError(f"Telegram trả về HTTP {r.status_code}") from None
    if not d.get("ok"):
        raise RuntimeError(d.get("description") or f"HTTP {r.status_code}")
    return d["result"]


def _time(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M %d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso or "")


def format_event(ev):
    """HTML cho Telegram."""
    text = f"{ICON.get(ev['level'], '')} <b>{html.escape(ev['title'])}</b>"
    if ev.get("message"):
        text += f"\n{html.escape(ev['message'])}"
    text += f"\n<i>{_time(ev.get('created_at'))} · Backup System</i>"
    if ev.get("ack"):
        text += f"\n✔ Đã xác nhận: <b>{ACK_TEXT.get(ev['ack'], ev['ack'])}</b>"
        if ev.get("ack_by"):
            text += f" ({html.escape(str(ev['ack_by']))}, {_time(ev.get('ack_at'))})"
    return text


def _buttons(event_id):
    return {"inline_keyboard": [[{"text": "✅ Bình thường", "callback_data": f"ack:{event_id}:binh_thuong"},
                                 {"text": "⚠️ Sự cố", "callback_data": f"ack:{event_id}:su_co"}]]}


def send_event(ev, buttons=True, force=False):
    """Gui mot su kien len Telegram (neu cau hinh). Tra ve message_id hoac None. force: bo qua 'bao khi thanh cong'."""
    global LAST_ERROR
    s = settings()
    if not (s["token"] and s["chat_id"]) or (not s["enabled"] and not force):
        LAST_ERROR = "Chưa cấu hình token / chat ID hoặc đang tắt thông báo"
        return None
    if ev["level"] in ("ok", "info") and not s["notify_ok"] and not force:
        return None
    try:
        m = telegram("sendMessage", s["token"], chat_id=s["chat_id"], text=format_event(ev), parse_mode="HTML",
                     reply_markup=_buttons(ev["id"]) if buttons else None)
        database.set_event_telegram(ev["id"], m["message_id"])
        LAST_ERROR = ""
        return m["message_id"]
    except (requests.RequestException, RuntimeError) as e:
        LAST_ERROR = str(e)
        log.warning("Không gửi được Telegram cho sự kiện #%s: %s", ev["id"], e)
        return None


def last_error():
    return LAST_ERROR


def after_web_ack(ev):
    """Quan tri xac nhan tren web -> sua tin Telegram tuong ung (bo 2 nut, ghi ket qua)."""
    if not ev.get("telegram_msg_id"):
        return
    s = settings()
    if not (s["token"] and s["chat_id"]):
        return

    def _edit():
        try:
            telegram("editMessageText", s["token"], chat_id=s["chat_id"], message_id=ev["telegram_msg_id"],
                     text=format_event(ev), parse_mode="HTML")
        except (requests.RequestException, RuntimeError) as e:
            log.info("Không sửa được tin Telegram của sự kiện #%s: %s", ev["id"], e)
    if SYNC:
        _edit()
    else:
        threading.Thread(target=_edit, daemon=True, name="telegram-edit").start()


def notify(kind, title, message="", level="info", user_id=None, data=None, buttons=True):
    """Ghi su kien + gui Telegram (thread nen). Tra ve su kien vua ghi."""
    ev = database.add_event(kind, title, message, level, user_id, data)
    if SYNC:
        send_event(ev, buttons)
    else:
        threading.Thread(target=send_event, args=(ev, buttons), daemon=True, name="telegram-send").start()
    return ev


# ---------------------------------------------------------------- su kien tu job / webhook
def job_finished(job, host=None, user_id=None):
    """Job agent vua ket thuc -> su kien. Tra ve su kien (hoac None neu khong dang chu y)."""
    jt, st, msg = job.get("job_type"), job.get("status"), job.get("message") or ""
    where = f" · {host}" if host else ""
    if st == "cancelled":
        return None
    if jt == "backup":
        if st == "completed":
            return notify("backup", f"Sao lưu xong{where}", msg, "ok", user_id, buttons=False)
        if "BẤT THƯỜNG" in msg.upper() or "BAT THUONG" in msg.upper():
            return notify("anomaly", f"CỔNG CHẶN BẤT THƯỜNG: đã dừng sao lưu{where}", msg, "err", user_id)
        return notify("backup", f"Sao lưu THẤT BẠI{where}", msg, "err", user_id)
    if jt == "restore":
        return notify("restore", ("Khôi phục xong" if st == "completed" else "Khôi phục THẤT BẠI") + where, msg,
                      "ok" if st == "completed" else "err", user_id, buttons=st != "completed")
    if jt == "verify":
        return notify("verify", ("Khôi phục thử: OK" if st == "completed" else "Khôi phục thử: LỖI") + where, msg,
                      "ok" if st == "completed" else "err", user_id, buttons=st != "completed")
    if jt == "check":
        return notify("kho", ("Kiểm tra kho: toàn vẹn" if st == "completed" else "Kiểm tra kho: CÓ LỖI") + where, msg,
                      "ok" if st == "completed" else "err", user_id, buttons=st != "completed")
    return None


def from_webhook(payload, user_id=None):
    """JSON tu `python -m core verify/backup --notify-url` hoac verify_sql_restore.ps1 -NotifyUrl."""
    t = str(payload.get("type") or "")
    host = payload.get("host") or ""
    where = f" · {host}" if host else ""
    if t == "verify":
        ok = payload.get("result") == "OK"
        msg = (f"{vn_int(payload.get('ok', 0))}/{vn_int(payload.get('checked', 0))} file khớp SHA-256, "
               f"{vn_mb(payload.get('bytes', 0))}, {vn_num(payload.get('seconds', 0), 1)} giây"
               f" (snapshot {str(payload.get('snapshot', ''))[:12]})")
        if not ok and payload.get("failed"):
            msg += "; lỗi: " + "; ".join(f"{f.get('path')}: {f.get('error')}" for f in payload["failed"][:3])
        return notify("verify", ("Khôi phục thử hằng tuần: OK" if ok else "Khôi phục thử hằng tuần: LỖI") + where, msg,
                      "ok" if ok else "err", user_id, data=payload, buttons=not ok)
    if t == "anomaly":
        reasons = "; ".join(payload.get("reasons") or [])
        msg = (f"{reasons}. {vn_int(payload.get('changed', 0))} file đổi, {vn_int(payload.get('added', 0))} thêm, "
               f"{vn_int(payload.get('removed', 0))} mất, {vn_int(payload.get('suspicious', 0))} nghi bị mã hoá.")
        return notify("anomaly", f"CỔNG CHẶN BẤT THƯỜNG: không gửi gì lên kho{where}", msg, "err", user_id, data=payload)
    if t == "verify_sql":
        ok = payload.get("result") == "OK"
        msg = f"CSDL {payload.get('database')} khôi phục ra {payload.get('restored_as')}, DBCC CHECKDB mã {payload.get('checkdb_exit')}, {payload.get('seconds')} giây"
        return notify("verify", ("Khôi phục thử CSDL: OK" if ok else "Khôi phục thử CSDL: LỖI") + where, msg,
                      "ok" if ok else "err", user_id, data=payload, buttons=not ok)
    title = str(payload.get("title") or payload.get("type") or "Thông báo")
    level = payload.get("level") if payload.get("level") in database.EVENT_LEVELS else "info"
    return notify(t or "khac", title + where, str(payload.get("message") or ""), level, user_id, data=payload)


# ---------------------------------------------------------------- nhan nut bam tu Telegram
class TelegramPoller(threading.Thread):
    """Long-poll getUpdates. Bam nut -> ack su kien + sua tin; /start, /id -> tra loi chat id."""

    def __init__(self, idle=10):
        super().__init__(name="telegram-poller", daemon=True)
        self.idle = idle
        self.offset = None
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            s = settings()
            if not (s["enabled"] and s["token"]):
                self._stop.wait(self.idle)
                continue
            try:
                for u in telegram("getUpdates", s["token"], http_timeout=40, offset=self.offset, timeout=30,
                                  allowed_updates=["message", "callback_query"]):
                    self.offset = u["update_id"] + 1
                    self.handle(u, s["token"])
            except (requests.RequestException, RuntimeError) as e:
                log.warning("Telegram getUpdates lỗi: %s", e)
                self._stop.wait(self.idle)
            except Exception:       # noqa: BLE001
                log.exception("TelegramPoller lỗi")
                self._stop.wait(self.idle)

    def handle(self, update, token):
        cq = update.get("callback_query")
        if cq:
            m = re.fullmatch(r"ack:(\d+):(binh_thuong|su_co)", str(cq.get("data") or ""))
            who = (cq.get("from") or {}).get("first_name") or (cq.get("from") or {}).get("username") or "Telegram"
            if not m or not database.get_event(int(m.group(1))):
                telegram("answerCallbackQuery", token, callback_query_id=cq["id"], text="Sự kiện không còn")
                return
            ev = database.ack_event(int(m.group(1)), m.group(2), who)
            telegram("answerCallbackQuery", token, callback_query_id=cq["id"], text=f"Đã ghi nhận: {ACK_TEXT[m.group(2)]}")
            msg = cq.get("message") or {}
            if msg.get("message_id"):
                try:
                    telegram("editMessageText", token, chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                             text=format_event(ev), parse_mode="HTML")
                except RuntimeError as e:
                    log.info("Không sửa được tin Telegram: %s", e)
            log.info("Telegram: %s xác nhận sự kiện #%s = %s", who, ev["id"], ev["ack"])
            return
        msg = update.get("message") or {}
        text = str(msg.get("text") or "").strip().lower()
        if text.startswith(("/start", "/id")) and msg.get("chat"):
            cid = msg["chat"]["id"]
            telegram("sendMessage", token, chat_id=cid, parse_mode="HTML",
                     text=f"Chat ID của bạn: <code>{cid}</code>\nDán vào Backup System → Cài đặt → Telegram rồi bấm Gửi tin thử.")


_poller = None


def start_poller():
    global _poller
    if _poller is None or not _poller.is_alive():
        _poller = TelegramPoller()
        _poller.start()
    return _poller
