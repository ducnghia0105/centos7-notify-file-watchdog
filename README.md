# centos7-notify-file-watchdog

"monitor": "on", => off khi làm việc vs code, server
  "debounce_seconds": 15, // 15s gửi thông báo tele 1 lần nếu phát hiện
  "watch_extensions": [".php", ".js", ".txt"],
  "themes": "flatsome1, flatsome2", // các theme allow xử lý file
  "telegram": {
    "bot_token": "token bot",
    "chat_id": "chat id"
  }
}


#Yêu cầu cài watchdog để theo dõi

#hướng dẫn
Thư mục /var/thienduccode


# 1.Tạo file service chạy tự động
nano /etc/systemd/system/thienduc-monitor-telegram.service

#chèn nội dung
[Unit]
Description=File Monitor Telegram
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/python3.6 /var/thienduccode/monitor.py
WorkingDirectory=/var/thienduccode
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target



# 2.Kích hoạt và chạy
#systemd systemctl daemon-reload
#systemctl enable thienduc-monitor-telegram
#systemctl start thienduc-monitor-telegram
#systemctl status thienduc-monitor-telegram

log
# Xem log realtime journalctl - thienduc-monitor-telegram -f

# Hoặc xem file log trực tiếp
tail -f /var/thienduccode/monitor.log
