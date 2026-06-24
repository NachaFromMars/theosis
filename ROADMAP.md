# Roadmap

Theosis hiện ở **v2.4.0** — đã hoàn tất 12/12 mục blueprint V2. Dưới đây là hướng đi tiếp, xếp theo giá trị. Không có cam kết thời gian; làm theo nhu cầu thực tế.

## ✅ Đã xong (v2.x)

Engine `fan-out → cross-audit → patch → merge`, async, provider-agnostic (OpenAI-compatible). Ngoài ra:

- Chống lỗi từng slot (retry + per-slot timeout + loại slot chết, không sập mẻ)
- Đo token/chi phí + trần token (budget guard)
- Hội tụ sớm (convergence early-stop)
- Hợp nhất có trọng số theo verdict (weighted merge)
- Multi-auditor M-of-N
- Pluggable strategies: `round_robin` / `all_vs_all` / `star`
- Executor: chạy code / check số làm ground truth (opt-in, sandbox best-effort)
- Streaming SSE cho `/v1/chat/completions`
- CLI (`python -m theosis`), packaging (`pyproject.toml`), web console, governance docs

## 🔜 Tiếp theo (giá trị cao)

- **Persistence + replay** — dump `trail` ra JSON, load lại để diff / A-B / eval. Có ích nhất nếu muốn benchmark các cấu hình (strategy, số vòng, model) một cách có hệ thống.
- **Convergence bằng embedding** — hiện so độ giống theo ký tự (difflib), rẻ nhưng thô. Nâng lên cosine của embedding để bắt "đồng nghĩa khác chữ".
- **Multi-turn cho endpoint OpenAI-compat** — hiện chỉ lấy message user cuối; giữ lịch sử hội thoại.

## 🎯 v3 — hướng đang chốt

- ✅ **Smart router** (v2.5.0, Phase A) — một MiddleLayer/dispatcher: phân loại task → chọn model + strategy + số vòng + executor. Validate cứng + fallback an toàn khi router lỗi. **Xong.**
- **"Before Theosis" view** — phơi toàn bộ quá trình nghị: thứ tự từng phản hồi, ai chấm ai, câu đổi qua từng vòng, flow chéo. Trail đã chứa sẵn dữ liệu; chủ yếu là dựng UI timeline. **Đây là thế mạnh lớn nhất so với Fugu (nó giấu, mình phơi).**
- **3 cảnh giới (preset + cost cap):** *DemiTheosis* (nhẹ: 2 model, 1 vòng, no executor, budget thấp) · *Theosis* (chuẩn) · *Beyond Theosis* (max: all model, all-vs-all, nhiều vòng, executor, budget cao).
- **Verifier++** — executor mạnh hơn: chạy unit test / lint / type-check, fact-check bằng web search; + vai MiddleLayer (Fact/Logic/Code Judge) chấm chéo. *Lưu ý: chấm chéo vẫn là LLM-soi-LLM; ground truth thật chỉ đến từ phần thực thi khách quan.*
- **Multi-judge (tùy chọn)** — nhiều model làm "quan chấm" cho A/B; gộp bằng vote/trung bình. Phải neo vào tín hiệu executor để chống thiên vị judge.

## 🌱 Mở rộng kiến trúc

- **Provider adapters** — tách `_call`/`_call_stream` thành package `providers/` (openai_compat, anthropic, ollama, …) để xử lý khác biệt từng nhà cung cấp gọn gàng.
- **Thêm strategies** — `tribunal` (mỗi giám khảo một chuyên môn), `debate` (tranh luận nhiều lượt), `red_team` (một nhóm phá, một nhóm vá).
- **Quality-gate metadata** — gắn vào final answer các tín hiệu: độ tin cậy, điểm bất đồng, nguồn mạnh nhất, mâu thuẫn chưa giải.

## 🔭 Tầm xa (sản phẩm sống, không có vạch đích)

- ✅ **Immune memory v1** (v2.6.0, Phase B) — Theosis học từ lỗi:
  - ✅ *Một model chuyên (rule-maker)*: sau khi bị user sửa → chưng cất thành **rule trừu tượng** (content-free) → lưu.
  - ✅ *Feedback loop*: lần sau inject rule liên quan vào MiddleLayer (fan-out), kèm event `memory`.
  - ✅ *Persistence content-free*: `MemoryStore` + `log_metrics()` content-free (nền eval/A-B). **Rule content-free từ thiết kế** — không persist nội dung gốc (có test bảo chứng).
  - ✅ *Eval harness* (v2.7.0): `python -m theosis.eval` — A/B baseline vs ký ức, ground truth qua `expect_contains` + executor pass-rate, verdict trung thực (cảnh báo mẫu nhỏ).
  - ✅ *Auto-learn từ executor-fail* (v2.7.0): executor bắt câu sai ở cuối → tự rút rule content-free (`verified=false`).
  - ✅ *Review/verify UI* (v2.8.0): tab "Ký ức" — duyệt/sửa/xoá rule; cổng `verified_only` chỉ tiêm rule đã duyệt. Teach tay = đã duyệt, auto-learn = chờ duyệt.
  - ✅ *Auto-learn đa nguồn* (v2.9.0): executor-fail (mạnh) + low-confidence + no-converge (yếu) — ưu tiên mạnh→yếu, 1 rule/lần, dedup-bump. Nguồn yếu an toàn nhờ cổng `verified_only`.
  - ✅ *Auto-demote từ eval* (v2.10.0): `eval_rules` đo hiệu ứng biên từng rule (ablation) → `auto_demote` loại rule có hại (giữ để review). CLI `--rules --demote`; UI hạ/khôi phục thủ công. Khép kín: thu nạp → lọc → đo → loại.
  - ✅ *Dashboard thống kê theo thời gian* (v2.11.0): `python -m theosis.stats` + tab "Thống kê" + `GET /api/stats` — sức khỏe rule, theo nguồn, hay dùng, lượt chạy & điểm TB theo ngày. Content-free.
  - ✅ *Đa phương thức I/O* (v2.12.0): upload mọi định dạng → tri giác thành text chia chung cho council (giữ bất biến MoA); xuất artifact (code block → file tải về). Endpoints `/api/upload`, `/api/files/{token}`.
  - ✅ *Council đa-lượt* (v2.13.0): luồng cả `messages[]` vào nghị bàn → hội thoại nhiều lượt; API stateless nên nhiều box hoạt động tự nhiên; UI tích luỹ hội thoại + nút trò chuyện mới. Van token: cửa sổ + cắt lịch sử.
  - ✅ *Tóm tắt hội thoại dài* (v2.14.0): nén lượt cũ thành tóm tắt + giữ cửa sổ lượt gần nhất; bật qua `summarize_history`.
  - ✅ *Sidebar nhiều box (localStorage)* (v2.14.0): nhiều hội thoại sống qua reload, lưu phía trình duyệt.
  - ⏳ *DB hội thoại* (đồng bộ đa thiết bị) — thuộc track production.
  - ⏳ *Hybrid thị giác + mô tả ảnh* (B): gửi ảnh raw cho slot có thị giác; OCR/mô tả ảnh thành text.
  - ⏳ *Hybrid thị giác + mô tả ảnh*: gửi ảnh raw cho slot có thị giác; mô tả/OCR ảnh thành text bằng model thị giác.
  - ⏳ **EdenTheosis** — đồng bộ rule liên-máy (federated). CHƯA làm: chỉ sau khi (a) chứng minh ký ức thật sự giúp bằng eval với model THẬT, và (b) cổng review/verify + content-free đủ vững. Chia sẻ rule chưa duyệt qua mạng = đúng rủi ro "rò rỉ chất xám" cần tránh.
- **EdenTheosis (kho tiến hoá liên kết — federated)** — opt-in: các Theosis tham gia đồng bộ "kinh nghiệm tiến hoá", một instance học → cả mạng cùng tiến. Tham vọng lớn, nhưng có **mâu thuẫn cốt lõi phải giải, không hứa suông**:
  - *Chia sẻ kinh nghiệm ⟺ riêng tư.* Mọi rule đều dẫn xuất từ dữ liệu thật của user. Vì vậy nguyên tắc cứng: **chỉ chia sẻ rule đã trừu tượng hoá, không bao giờ gửi query/answer/nội dung gốc**; và ngay cả rule trừu tượng vẫn có thể lộ (vd "khi hỏi về auth của Dự án X thì…") → cần redact + tổng quát hoá tại local, review-before-share, và **gộp qua nhiều user** để không truy ngược được cá nhân.
  - *Chống đầu độc (poisoning).* Pool chung có thể bị actor xấu nhồi rule hại → rule nhận về phải coi là **gợi ý được kiểm chứng lại tại local**, không tin mù; cần validation + reputation.
  - *Mô hình tin cậy.* "Đồng bộ cùng lúc" toàn mạng là bài toán hệ phân tán; phải chọn: federated thực sự (peer, không trung tâm) vs hub trung tâm — và ai vận hành, ai trả phí.
  - *Giữ đúng tinh thần Theosis*: minh bạch + local-first + **người dùng kiểm soát và xem được chính xác cái gì rời máy mình**. Consent phải là *informed* consent.
  - **Phụ thuộc**: chỉ làm sau khi immune memory chạy ổn trên MỘT instance và "rule" đã content-free từ thiết kế.
- **Preset chuyên ngành** — ví dụ hội đồng prompt điện ảnh (OUM Film Council).

---

> Triết lý: **đừng đắp tính năng không ai gọi.** Mỗi mục ở đây chỉ làm khi có nhu cầu thực tế chứng minh nó cần. Riêng EdenTheosis: **đừng build trước khi giải xong bài toán riêng tư** — một rò rỉ chất xám là phản bội chính lời hứa của nó.
