# Bot Discord Tóm Tắt Kênh Chat bằng Gemini AI

Bot tự động thu thập tin nhắn trong kênh theo khoảng thời gian bạn chỉ định và dùng Google Gemini API để tóm tắt các ý chính, diễn biến và việc cần làm (To-Do).

---

## 🚀 Cách cài đặt và chạy

### Bước 1: Điền API Key và Token
Mở file `.env` và điền:
- `DISCORD_TOKEN`: Token lấy từ Discord Developer Portal.
- `GEMINI_API_KEY`: API Key lấy từ Google AI Studio.

### Bước 2: Cài đặt thư viện (nếu chưa cài)
```bash
pip install -r requirements.txt
```

### Bước 3: Khởi chạy bot
```bash
python bot.py
```

---

## 💬 Hướng dẫn sử dụng trên Discord

Bạn có thể gọi bot bằng 3 cách:

### 1. Dùng lệnh Prefix `!tomtat`
- `!tomtat 30m` : Tóm tắt 30 phút gần nhất.
- `!tomtat 2h`  : Tóm tắt 2 giờ gần nhất.
- `!tomtat 1d`  : Tóm tắt 1 ngày vừa qua.
- `!tomtat`     : Mặc định tóm tắt 1 giờ gần nhất.

*(Có thể dùng `!summary` hoặc `!tt` thay cho `!tomtat`)*

### 2. Dùng Slash Command
- Gõ `/tomtat` và điền tham số thời gian (ví dụ: `30m`, `2h`, `1d`).

### 3. Tag bot trực tiếp (Mention)
- `@TênBot 45phut`
- `@TênBot 2h`

---

## ⏱️ Các đơn vị thời gian hỗ trợ:
- **Phút**: `m`, `min`, `phut`, `phút` (VD: `15m`, `30phut`)
- **Giờ**: `h`, `hr`, `gio`, `giờ` (VD: `1h`, `2gio`)
- **Ngày**: `d`, `day`, `ngay`, `ngày` (VD: `1d`, `2ngay`)
