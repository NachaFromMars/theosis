# Security Policy

## Phạm vi & mô hình triển khai

Theosis được thiết kế làm **công cụ chạy local, một người dùng**. Server (`theosis.server`) **không có lớp xác thực** — đừng phơi nó ra Internet công khai khi đã gắn API key thật. Nếu cần dùng chung, hãy đặt sau reverse proxy có auth, hoặc thêm lớp xác thực riêng.

## Quản lý khóa (API keys)

- Key của các slot khai báo trong `config.yaml` được nạp qua **biến môi trường** (`api_key_env`) — không ghi key thẳng vào file được commit.
- Model thêm từ UI lưu ở `slots.local.yaml`, đã nằm trong `.gitignore`, nên key **không** lọt vào git.
- `.env` cũng đã được `.gitignore` chặn.
- Trước khi publish/clone công khai: kiểm tra `git status` không có `.env` hay `slots.local.yaml`.

## Báo cáo lỗ hổng

Nếu phát hiện lỗ hổng bảo mật, vui lòng **không** mở issue công khai. Liên hệ riêng qua kênh của repo (GitHub Security Advisory hoặc email của maintainer). Mình sẽ phản hồi và phối hợp vá trước khi công bố.

## Phiên bản được hỗ trợ

| Phiên bản | Hỗ trợ |
|-----------|--------|
| 2.x       | ✅     |
| < 2.0     | ❌     |
