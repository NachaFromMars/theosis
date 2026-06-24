<div align="center">

# ✦ Theosis

**A self-improving council engine where multiple AI models draft, attack, repair, and merge into one answer.**

Theosis gửi mỗi câu hỏi tới nhiều model cùng lúc, cho chúng **chấm chéo** nhau theo một rubric phản biện, **tự vá**, lặp lại, rồi **hợp nhất** thành một câu trả lời duy nhất — có **chống lỗi từng slot**, **đo token/chi phí**, và **dừng sớm khi hội tụ**. Chạy local, có console web, và tự xuất ra một **API OpenAI-compatible**.

[![CI](https://github.com/NachaFromMars/theosis/actions/workflows/ci.yml/badge.svg)](https://github.com/NachaFromMars/theosis/actions/workflows/ci.yml) · MIT · Python ≥ 3.10 · by **NachaFromMars**

</div>

---

## Theosis là gì

Một câu trả lời từ một model lẻ có thể sai một cách tự tin. Ý tưởng của Theosis: cho nhiều model độc lập trả lời, rồi để chúng **soi lỗi của nhau** trước khi chốt — dựa trên hướng nghiên cứu *Mixture-of-Agents* và *multi-agent debate*.

Cách vận hành, 5 bước (toàn bộ async, các model chạy song song):

```
request
  │
  ├─[ Slot A · middlelayer → model ]─┐
  ├─[ Slot B · middlelayer → model ]─┤   fan-out (song song)
  │                                   │
  ▼                                   ▼
                 ans_A , ans_B
                      │
                      ▼   cross-audit   (B chấm A · A chấm B, theo rubric phản biện)
                 crit_A , crit_B
                      │
                      ▼   patch         (mỗi model tự sửa theo critique)
                 ans_A' , ans_B'
                      │
                      ▼   lặp  max_rounds
                      │
                      ▼   merge          (synthesizer giữ insight mạnh, không average)
                    final
```

> **Một sự thật thẳng thắn:** trần chất lượng = khả năng phân biệt đúng/sai của model **tổng hợp**, không phải tổng các model. Theosis mạnh nhất với câu **verify được** (code, toán, fact). Với câu diễn giải/sáng tạo thuần tuý, audit chéo có thể kéo về trung bình — hãy cân nhắc.

---

## Chạy thử trong 30 giây (không cần API key)

```bash
pip install -r requirements.txt
THEOSIS_DEMO=1 python run.py
```

Mở **http://localhost:8000** → gõ câu hỏi → bấm **Tinh luyện**. Chế độ demo dùng model giả lập để bạn xem trọn luồng và UI mà không tốn gì.

Hoặc dùng **CLI**:

```bash
python -m theosis "Đệ quy là gì?"             # in câu trả lời cuối
python -m theosis "..." --rounds 2 --json     # kèm trail (cost, scores, audit)
```

## Chạy thật

1. Cài đặt & cấu hình key:
   ```bash
   pip install -e ".[files]"   # kèm đọc PDF/docx/xlsx; bỏ [files] nếu chỉ cần text
   cp .env.example .env        # điền ANTHROPIC_API_KEY / OPENAI_API_KEY ...
   ```
2. Chỉnh `config.yaml` — mỗi slot tự cắm `base_url` + `api_key_env` + `model`. (Hoặc thêm model ngay trong UI; lưu ở `slots.local.yaml`.)
3. Chạy:
   ```bash
   python run.py               # http://localhost:8000
   # hoặc: uvicorn theosis.server:app --host 0.0.0.0 --port 8000
   ```

Bật/tắt tính năng trong `config.yaml > settings` hoặc ngay trên sidebar UI: router · executor · ký ức · tự học · chỉ-dùng-rule-đã-duyệt. Đo hiệu quả ký ức: `python -m theosis.eval tasks.json`. Thống kê: `python -m theosis.stats`.

---

## Cấu hình council (`config.yaml`)

Mỗi slot là một endpoint **OpenAI-compatible**. Thêm/bớt model chỉ là sửa YAML — **không đụng code**.

```yaml
slots:
  - name: opus
    model: claude-opus-4-8
    base_url: https://api.anthropic.com/v1
    api_key_env: ANTHROPIC_API_KEY
    system: "Bạn nghiêm ngặt, chính xác."
  - name: gpt
    model: gpt-4o
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY

aggregator:                    # model đứng ra tổng hợp = trần chất lượng
  name: aggregator
  model: claude-opus-4-8
  base_url: https://api.anthropic.com/v1
  api_key_env: ANTHROPIC_API_KEY

settings:
  max_rounds: 2
```

Base URL phổ biến (đều OpenAI-compatible): OpenAI `https://api.openai.com/v1` · Anthropic `https://api.anthropic.com/v1` · OpenRouter `https://openrouter.ai/api/v1` · DeepSeek `https://api.deepseek.com/v1` · xAI `https://api.x.ai/v1` · Groq `https://api.groq.com/openai/v1` · Ollama `http://localhost:11434/v1`.

**Mẹo:** dùng các model **khác họ** để có bất đồng thật khi audit; ba phiên bản cùng họ thường mắc lỗi giống nhau.

**Thêm model ngay trong UI:** bấm **＋ Thêm model** ở sidebar (preset sẵn OpenAI / Anthropic / OpenRouter / DeepSeek / xAI / Groq / Ollama, hoặc tuỳ chỉnh). Model thêm từ UI được lưu ở `slots.local.yaml` (đã gitignore) nên sống sót qua restart — và key **không** lọt vào `config.yaml`. Slot thêm kiểu này có nút ✕ để xoá; slot khai báo trong `config.yaml` thì quản lý trong file.

---

## API — Theosis như một model OpenAI

Server tự expose endpoint chuẩn OpenAI, nên mọi client OpenAI đều gọi được. `model = "theosis-v1"`.

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"theosis-v1","messages":[{"role":"user","content":"Xin chào"}]}'
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
r = client.chat.completions.create(
    model="theosis-v1",
    messages=[{"role": "user", "content": "Xin chào"}],
)
print(r.choices[0].message.content)
```

**Hội thoại nhiều lượt / nhiều "box":** API là *stateless* theo đúng chuẩn OpenAI — client giữ lịch sử và gửi cả mảng `messages` mỗi lượt; council nghị bàn trên toàn bộ hội thoại (lượt assistant = câu đã hợp nhất). "Nhiều box" = client giữ nhiều mảng `messages` riêng; server không cần trạng thái riêng cho từng box.

Vì là OpenAI-compatible, bạn có thể đặt chính Theosis làm **một slot bên trong một Theosis khác** (đệ quy nhiều tầng).

### Endpoints

| Method | Path | Mô tả |
|---|---|---|
| `GET`  | `/` | Console web |
| `POST` | `/v1/chat/completions` | OpenAI-compatible, **đa lượt** (gửi cả `messages`). `stream:true` để SSE. |
| `GET`  | `/v1/models` | Liệt kê model (`theosis-v1`) |
| `POST` | `/api/run` | Stream NDJSON đầy đủ tiến độ; nhận `history`, `file_tokens` |
| `POST` | `/api/upload` | Tải file (mọi định dạng) → token cho cả council đọc |
| `GET`  | `/api/files/{token}` | Tải file (upload hoặc artifact xuất ra) |
| `GET`  | `/api/stats` | Thống kê ký ức (rule + lượt chạy theo thời gian) |
| `GET`  | `/api/memory` · `/api/learn` · … | Quản lý ký ức (xem code) |
| `GET`  | `/api/config` · `/health` | Cấu hình UI · kiểm tra sống |

---

## Cấu trúc dự án

```
theosis/
├── theosis/
│   ├── models.py     # ModelSlot + MiddleLayer
│   ├── prompts.py    # RUBRIC · PATCH_SYS · MERGE_PROMPT
│   ├── core.py       # orchestrator (fan-out → audit → patch → merge)
│   ├── config.py     # nạp config YAML / demo mode
│   └── server.py     # FastAPI: API OpenAI-compat + console
├── web/index.html    # console (vanilla, không build)
├── tests/test_core.py
├── config.yaml · .env.example · requirements.txt · run.py
```

Chạy test (dùng mock, không cần key):

```bash
pip install pytest && pytest
```

---

## Tuỳ biến từng model (MiddleLayer)

Mỗi slot có một `MiddleLayer` riêng — chỗ để nâng cấp độc lập:

- `system` — prompt riêng cho slot (đã dùng trong `config.yaml`).
- `pre(request)` — sửa prompt **trước** khi gửi (cắm RAG, persona, reformat).
- `post(output)` — xử lý output **thô** (clean, trích JSON).

---

## Roadmap

**Xong ở v2 (12/12 blueprint) + V3-A/B/C/D:** chống lỗi từng slot · cost/token meter + budget guard · convergence early-stop · weighted merge · multi-auditor (M-of-N) · executor (ground-truth) · pluggable strategies · streaming SSE · CLI · packaging · **smart router** · **immune memory** (rule content-free) · **eval harness** (`python -m theosis.eval`) · **auto-learn đa nguồn** (executor-fail + chấm thấp + không hội tụ) · **review/verify** rule (tab Ký ức + cổng `verified_only`) · **auto-demote** rule có hại (học ngược từ eval, `--rules --demote`) · **dashboard thống kê** ký ức theo thời gian · **upload file mọi định dạng** (PDF/docx/xlsx/csv/text/ảnh → text chia chung cho cả council) + **xuất artifact** ra file tải về · **hội thoại đa lượt** (council nhớ ngữ cảnh; **sidebar nhiều box** lưu localStorage; **tóm tắt** hội thoại dài).

Hướng đi tiếp (persistence/replay, embedding convergence, provider adapters, immune memory…): xem [ROADMAP.md](ROADMAP.md).

---

## Đóng góp & bảo mật

- [ROADMAP.md](ROADMAP.md) — lộ trình phát triển
- [CHANGELOG.md](CHANGELOG.md) — lịch sử thay đổi
- [CONTRIBUTING.md](CONTRIBUTING.md) — cách setup & gửi PR
- [SECURITY.md](SECURITY.md) — chính sách bảo mật (lưu ý: server local, **chưa có auth** — đừng phơi ra Internet khi đã gắn key thật)

## License

MIT © 2026 **NachaFromMars** — xem [LICENSE](LICENSE).
