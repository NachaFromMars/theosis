"""Kho file vào/ra (plumbing) — lưu file tải lên + file xuất ra, ánh xạ token.

- Upload: lưu file thô + chạy tri giác (ingest) → giữ text để council đọc.
- Output: lưu file do run sinh ra (artifact) → phục vụ tải về.

Bản đồ token nằm trong bộ nhớ tiến trình (như STORE). Một tiến trình thì đủ; nhiều
worker cần DB/đối tượng dùng chung (track production — xem ROADMAP).
"""
from __future__ import annotations

import mimetypes
import os
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

from .ingest import IngestResult, format_attachments, ingest_bytes

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25MB / file
PREVIEW_CHARS = 600


def _base_dir() -> Path:
    base = Path(os.environ.get("THEOSIS_FILES", str(Path(tempfile.gettempdir()) / "theosis_files")))
    (base / "uploads").mkdir(parents=True, exist_ok=True)
    (base / "outputs").mkdir(parents=True, exist_ok=True)
    return base


class FileStore:
    def __init__(self, base: Optional[str] = None):
        if base:
            os.environ["THEOSIS_FILES"] = base
        self.base = _base_dir()
        self._uploads: dict = {}   # token -> {filename, kind, path, ingest}
        self._outputs: dict = {}   # token -> {filename, path}

    # ── uploads ──
    def add_upload(self, filename: str, data: bytes) -> dict:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"File quá lớn (> {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).")
        token = "u_" + uuid.uuid4().hex[:12]
        safe = Path(filename).name or "file"
        path = self.base / "uploads" / (token + "_" + safe)
        path.write_bytes(data)
        res: IngestResult = ingest_bytes(data, safe)
        self._uploads[token] = {"filename": safe, "kind": res.kind, "path": str(path), "ingest": res}
        return self._public(token, res, len(data))

    def _public(self, token: str, res: IngestResult, nbytes: int) -> dict:
        return {
            "token": token, "filename": res.filename, "kind": res.kind,
            "chars": res.chars, "truncated": res.truncated, "note": res.note,
            "needs_vision": res.needs_vision, "bytes": nbytes,
            "preview": (res.text[:PREVIEW_CHARS] if res.text else res.note),
        }

    def text_for(self, tokens: List[str]) -> str:
        """Ghép khối context dùng chung từ các file đã upload (theo token)."""
        results = [self._uploads[t]["ingest"] for t in (tokens or []) if t in self._uploads]
        return format_attachments(results)

    def uploads_meta(self, tokens: Optional[List[str]] = None) -> List[dict]:
        toks = tokens if tokens is not None else list(self._uploads)
        out = []
        for t in toks:
            u = self._uploads.get(t)
            if u:
                out.append({"token": t, "filename": u["filename"], "kind": u["kind"]})
        return out

    # ── outputs (artifact) ──
    def add_output(self, filename: str, data: bytes) -> dict:
        token = "o_" + uuid.uuid4().hex[:12]
        safe = Path(filename).name or "output"
        path = self.base / "outputs" / (token + "_" + safe)
        path.write_bytes(data)
        self._outputs[token] = {"filename": safe, "path": str(path)}
        return {"token": token, "filename": safe, "bytes": len(data),
                "url": f"/api/files/{token}"}

    # ── đọc để tải về (uploads hoặc outputs) ──
    def read(self, token: str):
        entry = self._outputs.get(token) or self._uploads.get(token)
        if not entry:
            return None
        p = Path(entry["path"])
        if not p.exists():
            return None
        media = mimetypes.guess_type(entry["filename"])[0] or "application/octet-stream"
        return p.read_bytes(), entry["filename"], media

    def clear(self):
        self._uploads.clear()
        self._outputs.clear()
