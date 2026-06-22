# Changelog

Theo [Keep a Changelog](https://keepachangelog.com/) và [SemVer](https://semver.org/).

## [2.0.0] — 2026-06-23

### Added
- **Packaging**: thêm `pyproject.toml` chuẩn (`build-backend = setuptools.build_meta`) → `pip install .` được; console script `theosis`.
- **CLI**: `python -m theosis "câu hỏi"` (cờ `--rounds`, `--json` để dump trail).
- **Resilient pipeline**: mỗi lời gọi model có **retry + per-slot timeout**; fan-out/audit/patch dùng `return_exceptions=True` → một model lỗi (timeout/401/429/5xx) bị **loại khỏi vòng**, không làm sập cả mẻ. Phát event `slot_error`.
- **Cost & token meter**: đọc `usage` từ response, cộng dồn vào `trail["cost"]` (tokens in/out, số call, ước tiền theo bảng giá mỗi model).
- **Token budget guard**: tham số `max_tokens_budget` → vượt thì cắt vòng, merge ngay với cái đang có (`stopped_reason="budget"`).
- **Convergence early-stop** (Phase 4): so độ tương đồng answer giữa hai vòng (difflib ratio); hội tụ ≥ ngưỡng → dừng sớm (`stopped_reason="converged"`).
- **Confidence scoring → weighted merge**: parse `VERDICT` (strong/mixed/weak) thành điểm, truyền vào merge để aggregator ưu tiên answer mạnh.
- **Governance**: `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`; LICENSE đứng tên NachaFromMars.

### Changed
- Lời gọi model cấp thấp trả `CompletionResult(text, model, usage, latency_ms)` thay vì chuỗi thuần.
- `done`/`fanout_done`/`audit_done`/`patch_done` event nay kèm `cost`; `done` kèm `scores`.
- `/v1/chat/completions` trả `usage` token thật (cộng từ các lời gọi con).

### Notes
- Các trường event mà UI đang đọc được giữ nguyên (tương thích ngược).
- "Bug pyproject build-backend" và "config.yaml mồ côi" trong feedback là về một bản repo cũ/khác — bản này dùng `config.py` + `load_config()` thật và không có lỗi đó.

## [1.0.0] — 2026-06-22

### Added
- Engine `fan-out → cross-audit → patch → merge`, async (`httpx` + `asyncio`).
- `ModelSlot` + `MiddleLayer` (pre/post hook mỗi slot); endpoint OpenAI-compatible, hỗ trợ mock mode.
- `config.yaml` (key qua env) + `slots.local.yaml` cho model thêm từ UI.
- Server FastAPI: API OpenAI-compat (`/v1/chat/completions`, `/v1/models`), `/api/run` (NDJSON stream), `/api/config`, thêm/xoá model.
- Web console: luồng tinh luyện live, badge verdict, thanh câu trả lời ghim, nút Dừng, cảnh báo thiếu key.
- `trail` lưu dấu vết mọi pha; bộ test mock.

## Roadmap (chưa làm)

- **Multi-auditor (M-of-N)**: mỗi answer ≥2 model soi.
- **Pluggable strategies**: `round_robin` / `all_vs_all` / `star` / `tribunal` / `debate` / `tournament` / `red_team`.
- **Provider adapters**: tách `_call` thành package `providers/` cho từng nhà cung cấp.
- **Streaming SSE** token-by-token cho `/v1/chat/completions`.
- **Persistence + replay**: dump/load `trail` để eval & A/B.
- **Immune memory**: ghi lại thất bại → sinh rule/patch tái dùng.
- **Preset OUM Film Council**: hội đồng chuyên prompt điện ảnh.
