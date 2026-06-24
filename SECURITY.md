# Security Policy

## Phạm vi & mô hình triển khai

Theosis được thiết kế làm **công cụ chạy local, một người dùng**. Server (`theosis.server`) **không có lớp xác thực** — đừng phơi nó ra Internet công khai khi đã gắn API key thật. Nếu cần dùng chung, hãy đặt sau reverse proxy có auth, hoặc thêm lớp xác thực riêng.

## Quản lý khóa (API keys)

- Key của các slot khai báo trong `config.yaml` được nạp qua **biến môi trường** (`api_key_env`) — không ghi key thẳng vào file được commit.
- Model thêm từ UI lưu ở `slots.local.yaml`, đã nằm trong `.gitignore`, nên key **không** lọt vào git.
- `.env` cũng đã được `.gitignore` chặn.
- Trước khi publish/clone công khai: kiểm tra `git status` không có `.env` hay `slots.local.yaml`.

## Executor — chạy code (opt-in, mặc định TẮT)

Khi bật `use_executor` (qua `config.yaml`, tham số API, hoặc toggle trên UI), Theosis sẽ **chạy code Python trích từ câu trả lời của model** để lấy ground truth cho audit.

- Tiến trình con chạy ở **Python isolated mode** (`-I`), trong **thư mục tạm**, có **timeout** và **giới hạn CPU/RAM** (POSIX).
- Nhưng **chạy code không tin cậy luôn có rủi ro** (đọc/ghi file trong quyền của bạn, gọi mạng…). Sandbox này là *best-effort*, **không phải** cô lập tuyệt đối.
- **Chỉ bật trên máy/tài khoản bạn kiểm soát.** Muốn an toàn hơn: chạy Theosis trong container/VM, hoặc tắt mạng cho tiến trình con ở môi trường triển khai.
- Mặc định **tắt** — không tự chạy gì nếu bạn không bật.

## Báo cáo lỗ hổng

Nếu phát hiện lỗ hổng bảo mật, vui lòng **không** mở issue công khai. Liên hệ riêng qua kênh của repo (GitHub Security Advisory hoặc email của maintainer). Mình sẽ phản hồi và phối hợp vá trước khi công bố.

## Phiên bản được hỗ trợ

| Phiên bản | Hỗ trợ |
|-----------|--------|
| 2.x       | ✅     |
| < 2.0     | ❌     |
