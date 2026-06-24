# Changelog

Theo [Keep a Changelog](https://keepachangelog.com/) và [SemVer](https://semver.org/).

## [2.14.0] — 2026-06-24 · Sidebar nhiều box + Tóm tắt hội thoại dài

### Added
- **Sidebar nhiều hội thoại (localStorage).** Mục **Hội thoại** ở đầu sidebar: liệt kê các box, bấm để chuyển, ✕ để xoá, **＋** tạo box mới. Mỗi box giữ lịch sử lượt riêng (`{role, content}`), sống qua reload trình duyệt. Box vừa dùng tự nhảy lên đầu; tiêu đề tự sinh từ câu hỏi đầu. Giới hạn 40 box × 60 lượt + chống JSON hỏng → `[]`. Tải lại một box hiện lịch sử dạng hỏi–đáp (bong bóng user + bong bóng trả lời); lượt mới vẫn xem được toàn bộ luồng nghị bàn.
  - *Lưu phía trình duyệt* (rẻ, không cần server); đồng bộ đa thiết bị vẫn cần DB (track production).
- **Tóm tắt hội thoại dài (`summarize_history`).** Khi lịch sử dài hơn cửa sổ, các lượt CŨ (ngoài cửa sổ) được **nén thành một tóm tắt** đặt trước N lượt gần nhất — giữ ngữ cảnh dài mà không phình token vô hạn.
  - Core: `_summarize_history()` + `_prepare_history_smart()`; thêm `summarize_history` vào `theosis()` / `theosis_stream()` (cộng cả chi phí lời gọi tóm tắt vào trail). Prompt `SUMMARIZER_SYS`.
  - Bật/tắt: `config.yaml > settings.summarize_history`, field trong `/api/run` + `/v1/chat/completions`, và toggle **"Tóm tắt hội thoại dài"** trên sidebar.
  - Chỉ tốn thêm **một** lời gọi model, và **chỉ khi** lịch sử thực sự dài hơn cửa sổ.

### Notes
- Box lưu *lịch sử hỏi–đáp* (không lưu toàn bộ luồng nghị bàn của các lượt cũ — luồng đó là phù du, chỉ hiện trực tiếp lúc chạy). Đây là lựa chọn có chủ đích để localStorage gọn nhẹ.
- Tóm tắt là lossy như mọi tóm tắt; cửa sổ N lượt gần nhất vẫn giữ nguyên văn để không mất chi tiết mới.

## [2.13.0] — 2026-06-24 · Council đa-lượt (multi-turn)

### Added
- **Council hội thoại nhiều lượt.** Toàn bộ lịch sử hội thoại được luồng vào nghị bàn (fan-out → patch → merge), không chỉ tin nhắn cuối. Lượt assistant trong lịch sử = câu đã hợp nhất (thứ user từng thấy).
  - Core: `theosis()` / `theosis_stream()` nhận `history` + `max_history_turns`; `ask_slot`/`patch`/`merge` chèn lịch sử **trước** lượt user hiện tại. (Audit không nhận lịch sử — tiết kiệm token ở bước nhiều lời gọi nhất; merge thấy lịch sử nên vẫn đảm bảo mạch hội thoại.)
  - `_prepare_history()`: cửa sổ N lượt gần nhất + cắt ký tự mỗi lượt → **chặn phình token** (mối lo chính của đa lượt).
- **API đa lượt đúng chuẩn OpenAI.** `/v1/chat/completions` giờ tách `history` = mọi message trước + `request` = tin nhắn user cuối (trước đây bỏ qua lịch sử). Vì stateless, **nhiều "box" hoạt động tự nhiên**: client giữ nhiều mảng `messages` riêng, server không cần trạng thái cho từng box. `/api/run` nhận field `history`.
- **UI đa lượt.** Web console tích luỹ hội thoại của box hiện tại, gửi `history` mỗi lượt, hiện **bong bóng câu hỏi** + ngăn cách lượt (luồng nghị bàn nối tiếp, không xoá). Nút **＋ Trò chuyện mới** xoá lịch sử + đính kèm để bắt đầu box mới.
- **Sẵn sàng chạy thật.** README "Chạy thật" cập nhật (`pip install -e ".[files]"`, `uvicorn theosis.server:app`); bảng endpoints bổ sung `/api/upload`, `/api/files/{token}`, `/api/stats`; kiểm chứng server boot ở chế độ thật (nạp slot từ `config.yaml`, serve UI, `/health`).

### Notes
- Token tăng theo lượt vì mỗi lượt chạy lại cả council — `_prepare_history` (cửa sổ + cắt) là van an toàn; *tóm tắt hội thoại bằng model* để dồn lịch sử dài là nâng cấp sau.
- Sidebar nhiều box lưu phía server (đồng bộ đa thiết bị) cần DB — vẫn thuộc track production.

## [2.12.0] — 2026-06-24 · Đa phương thức I/O (plumbing file)

### Added
- **Tải file lên cho cả council đọc — mọi định dạng, chia chung.** Lớp tri giác (`theosis/ingest.py`) chuẩn hoá mọi file về TEXT để các model dị chủng cùng nghị bàn trên một đầu vào (giữ bất biến MoA):
  - PDF (pypdf) · docx (python-docx) · xlsx (openpyxl) · csv/tsv (bảng) · txt/md/code/json/yaml (đọc thẳng) · ảnh (metadata + cờ `needs_vision`, chờ model thị giác) · fallback nhẹ nhàng khi thiếu lib hoặc định dạng lạ. Cắt mỗi file ở 20k ký tự để khỏi phình token.
  - Kho file (`theosis/files.py`): `FileStore` lưu upload + output trên đĩa, ánh xạ token, giới hạn 25MB/file.
  - Endpoints: `POST /api/upload` (multipart, nhiều file → token + metadata + preview), `GET /api/files/{token}` (tải về). `/api/run` nhận `file_tokens` → ghép context file (chia chung) vào trước prompt; phát event `attachments`.
- **Xuất file ra (artifact).** `extract_code_blocks()` trích code block trong câu trả lời cuối → lưu thành file tải về (map ngôn ngữ→đuôi), phát event `artifact` qua `/api/run`. (Trả file là extension riêng của Theosis, không qua `/v1/chat/completions` vì chuẩn OpenAI không có trường file-output.)
- **UI**: nút 📎 đính kèm + chip file (kind + xoá) + gửi `file_tokens`; render dòng `attachments` ("council đọc N tài liệu") + thẻ `artifact` có nút tải về.
- Deps: thêm `python-multipart` (core, cho upload) + extra `[files]` = pypdf, python-docx, openpyxl, Pillow.

### Notes
- Tri giác là **đồng nhất**: nghị bàn trên *mô tả/text* nên lossy với pixel (hỏi mã màu chính xác sẽ hỏng). Hybrid (gửi ảnh raw cho slot có thị giác) là nâng cấp sau. Mô tả ảnh bằng model thị giác cũng để bước sau — hiện ảnh vào ở dạng metadata + cờ `needs_vision`.
- Kho file & token map nằm trong tiến trình (như STORE) — nhiều worker cần DB/đối tượng dùng chung (track production).

## [2.11.0] — 2026-06-23 · V3 Phase G

### Added
- **Dashboard thống kê ký ức theo thời gian** (`theosis/stats.py`) — tổng quan sức khỏe ký ức, tất cả **content-free** (chỉ đếm/điểm/timestamp, không nội dung gốc):
  - `rule_stats(store)`: tổng rule, đã duyệt / chưa duyệt / bị hạ, sức khỏe (giúp / trung tính / hại theo `score`), theo nguồn, tổng lượt áp dụng, hay-dùng-nhất, **rule tạo theo ngày**.
  - `run_stats(metrics_path)`: tổng lượt chạy, **lượt chạy theo ngày**, ~tok/lần, loại task, **điểm TB theo ngày** — đọc từ `metrics.local.jsonl` (đã ghi từ Phase B). Thiếu file → rỗng an toàn.
  - `dashboard()` gộp cả hai; `format_dashboard()` in bảng ASCII (kèm bar chart lượt chạy theo ngày).
  - CLI: `python -m theosis.stats [--json]`.
- **Endpoint `GET /api/stats`** + **tab "Thống kê"** trên web console: thẻ số (tổng rule / đã duyệt / bị hạ / lượt chạy), thanh **sức khỏe rule** (giúp·trung tính·hại), **theo nguồn** (bar), **hay dùng nhất**, và **mini bar chart** lượt-chạy-theo-ngày + điểm-TB-theo-ngày (thuần CSS, không thư viện).

### Notes
- Giờ có thể *nhìn thấy* ký ức tiến hoá: rule sinh ra theo thời gian, lượt dùng, điểm hội đồng theo ngày có cải thiện không. Khép kín vòng quan sát cho V3.

## [2.10.0] — 2026-06-23 · V3 Phase F

### Added
- **Auto-demote rule — học ngược từ eval** — đo hiệu ứng *từng rule* rồi tự loại rule có hại:
  - `eval_rules()` (ablation): với mỗi rule, so **baseline (không ký ức)** vs **chỉ rule đó** trên task set → hiệu ứng biên (Δ tỉ lệ đúng nếu có ground truth, không thì Δ điểm). Chi phí O(rules × tasks × trials) — công cụ offline.
  - `auto_demote(store, report, threshold=-0.05)`: rule có marginal < ngưỡng → đánh dấu **`demoted`** (loại khỏi việc tiêm, **vẫn giữ để review**), cập nhật `score` cho mọi rule. Chỉ HẠ tự động — **không tự khôi phục** (đó là quyết định của người duyệt).
  - CLI: `python -m theosis.eval tasks.json --rules [--demote] [--threshold X]` — in bảng hiệu ứng từng rule (✓ giúp / ⊘ hại → hạ / · trung tính).
  - Rule có thêm `score` (hiệu ứng đo được) + `demoted` (bị loại). `relevant()` **luôn bỏ qua rule demoted** (kể cả khi `verified_only` tắt). Backward-compat: file ký ức cũ nạp được (field mới về default).
  - Server: `POST /api/memory/{id}/demote` (hạ/khôi phục thủ công). UI tab Ký ức: badge **⊘ bị hạ** + hiển thị **hiệu ứng** (điểm) + nút **⊘ Hạ / ↑ Khôi phục**.

### Notes
- Vòng đời khép kín: auto-learn (đa nguồn) **thu nạp** rule → review/verify **lọc thủ công** → eval **đo** → auto-demote **loại cái hại bằng dữ liệu**. Đây là cơ chế tự sửa dựa trên ground truth, không phải cảm tính.
- Trong mock, rule không đổi tính đúng nên marginal ≈ 0 → **không hạ bừa** (trung thực); tín hiệu thật cần model thật + `expect_contains` + nhiều `--trials`.

## [2.9.0] — 2026-06-23 · V3 Phase E

### Added
- **Auto-learn đa nguồn** — mở rộng tín hiệu "biết là cần học" ngoài executor, tất cả qua một `_learn_signal` ưu tiên **MẠNH → YẾU** (chỉ MỘT rule/lần chạy):
  1. `auto:executor_fail` — ground truth bắt câu sai (mạnh, như cũ).
  2. `auto:low_confidence` — cả hội đồng tự chấm thấp (điểm tốt nhất < ngưỡng `low_confidence_threshold`, mặc định 0.35) → rút bài học từ critique. *Tín hiệu yếu (LLM chấm).*
  3. `auto:no_converge` — chạy hết ≥2 vòng mà vẫn không hội tụ (task khó/mơ hồ). *Tín hiệu yếu.*
  - Tất cả rule auto-learn vào ở trạng thái **chưa duyệt** (`verified=false`) → đi qua cổng review/verify (Phase D). Nguồn yếu an toàn vì có cổng lọc. UI: thẻ `learned` hiển thị đúng nguồn (executor / chấm thấp / không hội tụ).
- **Dedup-bump** (`MemoryStore.add_rule(dedup=True)`) — cùng một bài học bị học lại → **tăng `uses`**, không nhân bản. Auto-learn dùng dedup để giảm nhiễu; lặp lại = củng cố.

### Notes
- Một toggle `auto_learn` bật cả ba nguồn; phân biệt qua `rule.source` để review/lọc. Nguồn yếu (chấm thấp / không hội tụ) **bắt buộc** dựa vào cổng `verified_only` để không làm hại — đúng nguyên tắc "LLM chấm LLM thì phải có người gác".

## [2.8.0] — 2026-06-23 · V3 Phase D

### Added
- **Review/Verify UI cho rule** — human-in-the-loop cho ký ức:
  - Tab **"Ký ức"** mới: liệt kê mọi rule (guidance · nguồn · loại · số lần dùng · ngày · trạng thái duyệt), với nút **✓ Duyệt / Bỏ duyệt**, **✎ Sửa** (sửa guidance tại chỗ), **🗑 Xoá**, và **Xoá tất cả**.
  - Store: `set_verified()`, `update_guidance()`, `relevant(verified_only=...)`. Server: `POST /api/memory/{id}/verify`, `PATCH /api/memory/{id}`.
- **Cổng chất lượng `verified_only`** (opt-in, mặc định **tắt**) — bật = **chỉ tiêm rule đã duyệt** vào prompt; rule auto-learn chưa duyệt bị bỏ qua cho tới khi người dùng duyệt. Toggle ở sidebar + cờ cho `/api/run` + `/v1`.
- Rule do **người dạy tay** (`/api/learn`) giờ vào ở trạng thái **đã duyệt** (`verified=true`, human-in-the-loop); rule **auto-learn** vẫn **chưa duyệt** (`verified=false`) — chờ review.

### Fixed
- `/api/config` giờ lộ **đầy đủ settings** (strategy · use_router · use_memory · auto_learn · verified_only · …) qua một `DEFAULT_SETTINGS` chung. Trước đây ở chế độ demo chỉ lộ `max_rounds`, khiến toggle trên UI luôn khởi tạo OFF dù `config.yaml` bật — nay demo và chế độ thật nhất quán.

## [2.7.0] — 2026-06-23 · V3 Phase C

### Added
- **Eval harness có hệ thống** (`theosis/eval.py`, CLI offline) — đo ký ức **thực sự giúp hay hại**:
  - Chạy mỗi task HAI lần cùng cấu hình: baseline (tắt ký ức) vs treatment (bật ký ức) → so sánh.
  - Tín hiệu mạnh: `expect_contains` (ground truth do người viết task đặt) + executor pass-rate. Điểm thẩm định (LLM chấm) chỉ là proxy yếu — báo cáo **nói rõ** và cảnh báo khi mẫu nhỏ/thiếu ground-truth.
  - `EvalTask` · `run_eval()` · `EvalReport` · `load_tasks()` (JSON) · `format_report()` (bảng A/B + Δ + verdict). `--trials N` để giảm nhiễu.
  - CLI: `python -m theosis.eval eval_tasks.example.json [--trials N --rounds R --no-executor]`. Kèm `eval_tasks.example.json`.
- **Auto-learn từ executor-fail** (opt-in `auto_learn`, mặc định **tắt**) — khi executor (ground truth) bắt một câu trả lời **vẫn SAI ở cuối** vòng nghị, Theosis tự chưng cất một rule content-free (`source="auto:executor_fail"`, `verified=false`).
  - `_pick_failure()` (thuần) chọn câu fail; core gọi `make_rule` → `trail["learned"]` + event `learned`. Server persist vào STORE (`/api/run` + `/v1` non-stream). Best-effort: lỗi auto-learn không phá run.
  - UI: toggle "Tự học từ lỗi" + thẻ event `learned`. Chỉ học khi lỗi **sống tới câu trả lời cuối** (council vá được giữa chừng thì thôi).

### Notes
- Auto-learn cần `use_executor` (không có ground truth thì không kích hoạt). Rule auto-learn **chưa verified** — nên review; là cổng chặn trước khi chia sẻ (Eden).
- Eval trong mock chỉ chứng minh **bộ máy** (hai arm chạy, đo, tính Δ); tín hiệu thật cần model thật + `expect_contains`.

## [2.6.0] — 2026-06-23 · V3 Phase B

### Added
- **Immune Memory v1** (opt-in `use_memory`, mặc định **tắt**) — Theosis bắt đầu *học* từ lỗi:
  - `memory.py` (thuần, chỉ file I/O): `MemoryStore` lưu **rule trừu tượng** (`Rule`: guidance · task_type · keywords · uses · verified) + `relevant()` lấy rule liên quan theo task_type/keyword + `parse_rule()` + `format_rules_for_prompt()`.
  - `make_rule()` (core) gọi một **rule-maker** (prompt `RULEMAKER_SYS`) chưng cất một câu trả lời sai → một bài học CHUNG. Bài học được **tiêm vào fan-out** qua MiddleLayer (`memory_rules` → `ask_slot(lessons=...)`), kèm event `memory` + `trail["memory"]`.
  - **NGUYÊN TẮC CỨNG — content-free by design:** store KHÔNG bao giờ ghi query/answer/correction gốc xuống đĩa; chỉ rule đã trừu tượng hoá. Raw content chỉ nằm thoáng qua trong prompt rule-maker rồi bỏ. (Để sau nối EdenTheosis không phải retrofit privacy.) Có test bảo chứng: secret cấy vào input KHÔNG xuất hiện trong file rule/metrics.
  - `log_metrics()` — log **content-free** mỗi lần chạy (task_type · n_models · rounds · cost · scores), nền cho eval/A-B.
  - Server: `POST /api/learn` (dạy bài học từ câu sai), `GET /api/memory`, `DELETE /api/memory/{id}` (hoặc `/all`); cờ `use_memory` cho `/api/run` + `/v1` (kèm bump_uses + log metrics).
  - UI: toggle "Dùng ký ức" + badge đếm rule + thẻ event ký ức + ô **"Dạy bài học"** ngay dưới câu trả lời (gửi /api/learn).

### Notes
- `verified=false` trên rule mới — cổng duyệt-trước-khi-chia-sẻ cho Eden sau này.
- **Caveat trung thực:** schema store là content-free, nhưng nếu một model *thật* lỡ nhét chi tiết cụ thể vào TEXT guidance thì chi tiết đó có thể bị lưu — giảm thiểu bằng prompt rule-maker nghiêm ngặt + cờ `verified` (review sau). Ký ức chỉ thêm giá trị trên task lặp lại / kiểm chứng được.

## [2.5.0] — 2026-06-23 · V3 Phase A

### Added
- **Smart Router** (opt-in `use_router`, mặc định **tắt**) — một model làm "dispatcher": phân loại task → chọn **model nào** + **strategy** + **số vòng** + **executor** cho từng câu. Né "fan-out hết cho mọi câu".
  - `router.py` thuần (không I/O): `build_roster()` + `parse_plan()` **validate cứng** — bỏ slot không tồn tại, strategy bậy → mặc định, rounds clamp 0–3, rút JSON khỏi văn xuôi.
  - **Fallback an toàn**: router lỗi/đọc không được → giữ nguyên cấu hình đang có (`routed=false`), không bao giờ làm hỏng pipeline.
  - Phát event `route` + lưu `trail["route"]`; UI có toggle "Tự định tuyến" và thẻ hiển thị quyết định (task · model đã chọn · chiến lược · vòng · lý do).
  - Chọn slot làm router qua `config.yaml` (`router:`) hoặc mặc định dùng aggregator. Hoạt động cho cả `/api/run`, `/v1` (stream và non-stream).

### Notes
- Router **chỉ chạy khi bật**; tắt thì `trail["route"]` = null và pipeline y hệt trước (tương thích ngược).

## [2.4.0] — 2026-06-23

### Added
- **Streaming** câu trả lời cuối token-by-token:
  - `theosis_stream()` — async generator yield từng mẩu của câu trả lời cuối (merge được stream từ aggregator). Các pha nghị (fan-out/audit/patch) vẫn quan sát được qua `on_event`.
  - `/v1/chat/completions` với `"stream": true` → trả **SSE chuẩn OpenAI** (`chat.completion.chunk` … `[DONE]`), client OpenAI dùng được.
  - `_call_stream()` đọc SSE từ upstream OpenAI-compatible; mock thì mô phỏng streaming.
- Tách `_deliberate()` dùng chung cho cả `theosis()` và `theosis_stream()` (không nhân đôi orchestrator).
- **CI** GitHub Actions (`ruff` + `pytest`, Python 3.10–3.12) và **ROADMAP.md**.

### Notes
- Checklist 12 mục của blueprint: **hoàn tất** (SSE là mục cuối). Còn lại đều là roadmap mở rộng (persistence/replay, convergence embedding, provider adapters, immune memory…), không nằm trong 12.
- Console web vốn đã stream *quá trình* nghị (từng voice card). SSE phục vụ client gọi API ngoài.

## [2.3.0] — 2026-06-23

### Added
- **Pluggable strategies** — tách "ai chấm ai" thành chiến lược cắm được trong `strategies.py`:
  - `round_robin` (mặc định): mỗi câu bị `auditors_per_answer` slot kế tiếp soi.
  - `all_vs_all`: mỗi câu bị MỌI model khác soi (kỹ nhất, tốn nhất).
  - `star`: một giám khảo trung tâm soi tất cả, chính nó do á quân soi.
  - Chọn qua `strategy` (param/`config.yaml`/dropdown UI). Thêm chiến lược = thêm một hàm cùng chữ ký rồi đăng ký vào `STRATEGIES`.

### Notes
- Trail/event không đổi cấu trúc (vẫn `pairs` + `reviews`), nên UI render đa-thẻ sẵn có dùng được cho mọi chiến lược.
- Roadmap còn: **streaming SSE** và **persistence/replay**.

## [2.2.0] — 2026-06-23

### Added
- **Executor (ground-truth verifiers)** — opt-in (`use_executor`, mặc định **tắt**). Chạy code Python trích từ câu trả lời (sandbox best-effort: Python isolated mode + thư mục tạm + timeout + rlimit CPU/RAM trên POSIX) và **check số học** an toàn (chỉ `+-*/`, không tên/hàm).
  - Kết quả kiểm chứng được **đút vào prompt audit** (auditor chấm dựa trên kết quả thực tế) và **đút vào merge**.
  - **Ảnh hưởng điểm tin cậy**: câu thất bại kiểm chứng → điểm ép xuống ≤ 0.15 (dù LLM khen); câu qua kiểm chứng → nâng ≥ 0.7.
  - Phát event `evidence`; lưu `trail["evidence"]`. UI có toggle "Chạy code để kiểm chứng" (kèm cảnh báo) và hiện ✓/✗ từng câu.
- `SECURITY.md` thêm mục riêng về rủi ro chạy code.

### Notes
- Executor là thứ **thực sự nâng chất lượng** cho câu verify được (code/toán) — không chỉ LLM chấm LLM. Với câu diễn giải thuần thì nó "na" (bỏ qua), không ảnh hưởng.

## [2.1.0] — 2026-06-23

### Added
- **Multi-auditor (M-of-N)**: mỗi câu trả lời có thể bị **k model** soi thay vì 1 (`auditors_per_answer`, mặc định 1 = round-robin cũ). Engine `audit_assignments()` tự clamp k vào `[1, n-1]`. UI có stepper "Người chấm / câu"; mỗi review hiện thành một thẻ riêng kèm verdict.
- **Bảng giá ra config**: `pricing:` trong `config.yaml` (model → `[in, out]` USD/1M token), nạp qua `metrics.set_cost_table()`; model không liệt kê dùng giá mặc định.
- `trail["rounds"][i]["reviews"]` lưu chi tiết từng lượt soi (auditor, critique, verdict); score mỗi câu = trung bình verdict các auditor.

### Notes
- **License**: đã verify bằng lệnh — `LICENSE`, `pyproject` (`license` + classifier) và `README` đều **MIT**, nhất quán. Không có Apache ở đâu cả; báo cáo "license mismatch (Apache)" là về một bản repo khác, nên **không sửa** (sửa theo sẽ tạo mismatch thật).

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

- **Pluggable strategies**: `round_robin` / `all_vs_all` / `star` / `tribunal` / `debate` / `tournament` / `red_team`.
- **Convergence bằng embedding** (hiện dùng difflib theo ký tự).
- **Provider adapters**: tách `_call` thành package `providers/` cho từng nhà cung cấp.
- **Streaming SSE** token-by-token cho `/v1/chat/completions`.
- **Persistence + replay**: dump/load `trail` để eval & A/B.
- **Immune memory**: ghi lại thất bại → sinh rule/patch tái dùng.
- **Preset OUM Film Council**: hội đồng chuyên prompt điện ảnh.
