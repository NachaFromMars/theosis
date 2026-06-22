<div align="center">

# ✦ Theosis

**A self-improving council engine where multiple AI models draft, attack, repair, and merge into one answer.**

Theosis gửi mỗi câu hỏi tới nhiều model cùng lúc, cho chúng **chấm chéo** nhau theo một rubric phản biện, **tự vá**, lặp lại, rồi **hợp nhất** thành một câu trả lời duy nhất — có **chống lỗi từng slot**, **đo token/chi phí**, và **dừng sớm khi hội tụ**. Chạy local, có console web, và tự xuất ra một **API OpenAI-compatible**.

`MIT` · by **NachaFromMars**

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
   pip install -e .            # hoặc: pip install -r requirements.txt
   cp .env.example .env        # điền ANTHROPIC_API_KEY / OPENAI_API_KEY ...
   ```
2. Chỉnh `config.yaml` — mỗi slot tự cắm `base_url` + `api_key_env` + `model`.
3. Chạy:
   ```bash
   python run.py               # http://localhost:8000
   ```

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

Vì là OpenAI-compatible, bạn có thể đặt chính Theosis làm **một slot bên trong một Theosis khác** (đệ quy nhiều tầng).

### Endpoints

| Method | Path | Mô tả |
|---|---|---|
| `GET`  | `/` | Console web |
| `POST` | `/v1/chat/completions` | OpenAI-compatible (trả câu trả lời cuối). Body nhận thêm `max_rounds`. |
| `GET`  | `/v1/models` | Liệt kê model (`theosis-v1`) |
| `POST` | `/api/run` | Stream NDJSON đầy đủ tiến độ (fan-out → audit → patch → merge) cho UI |
| `GET`  | `/api/config` | Cấu hình council cho UI |
| `GET`  | `/health` | Kiểm tra sống |

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

**Xong ở v2:** ✅ convergence early-stop · ✅ cost/token meter + budget guard · ✅ chống lỗi từng slot (retry + drop) · ✅ weighted merge (theo verdict) · ✅ CLI · ✅ pyproject (pip install).

**Còn lại** (xem [CHANGELOG.md](CHANGELOG.md)): executor cho câu verify được · multi-auditor (M-of-N) · pluggable strategies (`all_vs_all` / `star` / `tribunal` / `debate`) · streaming SSE · persistence + replay · immune memory · multi-turn cho endpoint OpenAI-compat.

---

## Đóng góp & bảo mật

- [CHANGELOG.md](CHANGELOG.md) — lịch sử thay đổi + roadmap
- [CONTRIBUTING.md](CONTRIBUTING.md) — cách setup & gửi PR
- [SECURITY.md](SECURITY.md) — chính sách bảo mật (lưu ý: server local, **chưa có auth** — đừng phơi ra Internet khi đã gắn key thật)

## License

MIT © 2026 **NachaFromMars** — xem [LICENSE](LICENSE).
