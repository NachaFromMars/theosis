# Contributing to Theosis

Cảm ơn bạn quan tâm đến Theosis 🐺

## Bắt đầu

```bash
git clone https://github.com/NachaFromMars/theosis
cd theosis
pip install -e ".[dev]"     # cài kèm pytest, ruff
```

Chạy thử không cần key:

```bash
THEOSIS_DEMO=1 python run.py        # UI tại http://localhost:8000
python -m theosis "Đệ quy là gì?"   # CLI (cũng chạy demo nếu THEOSIS_DEMO=1)
```

## Kiểm thử

Toàn bộ test dùng **mock mode** nên không cần API key:

```bash
pytest -q
ruff check .
```

Mỗi PR phải:
- `pytest` xanh
- `ruff check .` sạch
- Thêm test cho hành vi mới (đặc biệt là engine core)

## Cấu trúc

```
theosis/
├── core.py       # orchestrator: fan-out → audit → patch → merge
├── metrics.py    # CompletionResult, cost meter, convergence, scoring
├── models.py     # ModelSlot + MiddleLayer
├── prompts.py    # RUBRIC · PATCH_SYS · MERGE_PROMPT
├── config.py     # nạp config YAML + slots.local.yaml
├── server.py     # FastAPI: API OpenAI-compat + console
└── __main__.py   # CLI: python -m theosis
web/index.html    # console (vanilla, không build)
```

## Quy ước

- Python ≥ 3.10, dòng tối đa 100 ký tự (ruff).
- Engine giữ **provider-agnostic**: mọi model đi qua một lời gọi OpenAI-compatible `/chat/completions`.
- Đừng phá các trường event mà UI đang đọc (`fanout_done.answers`, `audit_done.critiques/pairs`, `patch_done.answers`, `done.final/trail`). Thêm trường mới thì được.
- Không commit `.env` hay `slots.local.yaml`.

## Báo lỗi / đề xuất

Mở issue với mô tả rõ ràng, các bước tái hiện, và (nếu được) log. Đề xuất tính năng nên nêu *vấn đề người dùng* trước, giải pháp sau.
