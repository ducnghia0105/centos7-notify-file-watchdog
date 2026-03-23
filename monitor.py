import os
import sys
import time
import json
import logging
import threading
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(SCRIPT_DIR, "config.json")
PENDING_FILE = os.path.join(SCRIPT_DIR, ".pending_events.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(SCRIPT_DIR, "monitor.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

_pending_lock = threading.Lock()
_send_timer   = None


# ===== LOAD CONFIG =====
def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        log.error(f"Không tìm thấy config: {CONFIG_FILE}")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Config JSON lỗi: {e}")
        return None


# ===== TELEGRAM =====
def send_telegram(msg, config):
    try:
        bot_token = config['telegram']['bot_token']
        chat_id   = config['telegram']['chat_id']
        url  = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        result = resp.json()
        if not result.get("ok"):
            log.error(f"Telegram lỗi: {result}")
        else:
            log.info(f"Telegram OK: {msg[:60]}")
    except requests.exceptions.ConnectionError:
        log.error("Telegram: Không có mạng")
    except requests.exceptions.Timeout:
        log.error("Telegram: Timeout")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


# ===== BATCH – gom event vào file tạm, gửi 1 lần =====
def queue_message(msg, config):
    """
    Thêm msg vào pending file.
    Timer chỉ start 1 lần khi event đầu tiên đến.
    Các event tiếp theo trong cùng window chỉ ghi thêm vào file, không reset timer.
    """
    global _send_timer
    seconds = float(config.get("debounce_seconds", 5))

    with _pending_lock:
        events = []
        try:
            if os.path.exists(PENDING_FILE):
                with open(PENDING_FILE) as f:
                    events = json.load(f)
        except:
            events = []

        events.append(msg)

        with open(PENDING_FILE, 'w') as f:
            json.dump(events, f, ensure_ascii=False)

        # Chỉ start timer nếu chưa có timer đang chạy
        if _send_timer is None:
            _send_timer = threading.Timer(seconds, _flush_and_send, args=[config])
            _send_timer.daemon = True
            _send_timer.start()
            log.info(f"⏳ Sẽ gửi Telegram sau {seconds}s")


def _flush_and_send(config):
    global _send_timer
    with _pending_lock:
        _send_timer = None
        try:
            if not os.path.exists(PENDING_FILE):
                return
            with open(PENDING_FILE) as f:
                events = json.load(f)
            os.remove(PENDING_FILE)
        except Exception as e:
            log.error(f"Flush error: {e}")
            return

    if not events:
        return

    if len(events) == 1:
        final_msg = events[0]
    else:
        final_msg = f"📋 {len(events)} sự kiện:\n\n" + "\n\n".join(events)

    send_telegram(final_msg, config)


# ===== FILTERS =====
def is_watched_extension(path, config):
    exts = config.get("watch_extensions", [".php", ".js"])
    return any(path.endswith(ext) for ext in exts)


def get_type(path):
    if "/plugins/" in path:
        return "plugin"
    if "/themes/" in path:
        return "theme"
    return "normal"


def should_watch_theme(path, config):
    if "/themes/" not in path:
        return True
    allowed = [x.strip() for x in config.get("themes", "").split(",") if x.strip()]
    for theme in allowed:
        if f"/themes/{theme}/" in path or path.endswith(f"/themes/{theme}"):
            return True
    return False


# ===== XỬ LÝ EVENT =====
def process_event(path, action, config):
    # Bỏ qua file đã được rename bởi chính script
    if "___001" in path:
        return

    # Chỉ xử lý path nằm trong public_html
    if "/public_html" not in path:
        return

    if not is_watched_extension(path, config):
        return

    if not should_watch_theme(path, config):
        log.debug(f"Theme không trong whitelist: {path}")
        return

    file_type = get_type(path)
    log.info(f"{action} [{file_type}] {path}")

    if file_type == "normal":
        queue_message(f"📄 {action}\n{path}", config)

    else:
        if action == "CREATED":
            new_path = path + "___001"
            try:
                if os.path.exists(path):
                    os.rename(path, new_path)  # rename ngay lập tức, không chờ timer
                    queue_message(
                        f"{file_type.upper()} ADD ⚠️\n{path}\n→ {new_path}",
                        config
                    )
                else:
                    log.warning(f"File không còn tồn tại: {path}")
            except Exception as e:
                log.error(f"Rename lỗi: {e}")
                queue_message(f"Rename error:\n{path}\n{e}", config)
        else:
            queue_message(f"{file_type.upper()} MODIFY ✏️\n{path}", config)


# ===== HANDLER =====
class Handler(FileSystemEventHandler):

    def handle(self, path, action):
        log.debug(f"RAW: {action} → {path}")
        config = load_config()
        if not config or config.get("monitor") != "on":
            return
        process_event(path, action, config)

    def on_created(self, event):
        if not event.is_directory:
            self.handle(event.src_path, "CREATED")

    def on_modified(self, event):
        if not event.is_directory:
            self.handle(event.src_path, "MODIFIED")

    # FTP upload tạo file tạm rồi rename → bắt on_moved
    def on_moved(self, event):
        if not event.is_directory:
            log.debug(f"RAW MOVED: {event.src_path} → {event.dest_path}")
            self.handle(event.dest_path, "CREATED")


# ===== MAIN =====
def main():
    config = load_config()
    if not config:
        log.error("Không đọc được config.json – dừng lại")
        sys.exit(1)

    send_telegram("🟢 Monitor started!", config)

    observer  = Observer()
    handler   = Handler()
    base_path = "/home"
    total     = 0

    for user in os.listdir(base_path):
        user_home   = os.path.join(base_path, user)
        public_html = os.path.join(user_home, "public_html")

        if os.path.isdir(public_html):
            # Watch user_home thay vì public_html
            # → public_html trở thành subdir → watchdog bắt event cả ở root public_html
            observer.schedule(handler, user_home, recursive=True)
            log.info(f"[+] Watching: {user_home}  (public_html)")
            total += 1

    if total == 0:
        log.error("Không tìm thấy public_html nào!")
        sys.exit(1)

    log.info(f"🚀 Total sites: {total}")
    observer.start()

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("Dừng monitor...")
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()

## Tóm tắt logic batch
# Event 1 (t=0s)  → ghi vào .pending_events.json → start timer 15s
# Event 2 (t=3s)  → ghi vào .pending_events.json → timer đang chạy, bỏ qua
# Event 3 (t=8s)  → ghi vào .pending_events.json → timer đang chạy, bỏ qua
# t=15s           → đọc file, gửi 1 tin "📋 3 sự kiện" → xoá file