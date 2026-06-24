"""Ground-truth verifiers: run code / check arithmetic to anchor audits in reality.

⚠️ SECURITY: ``run_python`` EXECUTES model-generated code in a subprocess. It is
OPT-IN (``use_executor=True``) and best-effort sandboxed (Python isolated mode,
a temp working dir, a wall-clock timeout, and CPU/memory rlimits on POSIX), but
running untrusted code is inherently risky. Only enable it on a machine/account
you control. See SECURITY.md.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from typing import List

_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_python(text: str) -> List[str]:
    """Lấy các khối ```python ... ``` (hoặc ``` ... ```) không rỗng."""
    return [b.strip() for b in _CODE_BLOCK.findall(text or "") if b.strip()]


def _posix_limits():
    """preexec_fn đặt giới hạn CPU/RAM cho tiến trình con (chỉ POSIX)."""
    try:
        import resource

        def _set():
            resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))

        return _set
    except Exception:  # pragma: no cover
        return None


def run_python(code: str, timeout: float = 6.0) -> dict:
    """Chạy đoạn code trong subprocess cô lập. Trả status pass/fail + stdout/stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=_posix_limits() if os.name == "posix" else None,
                env={"PATH": os.environ.get("PATH", "")},
            )
            ok = proc.returncode == 0
            return {
                "status": "pass" if ok else "fail",
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[-1500:],
                "stderr": (proc.stderr or "")[-1500:],
            }
        except subprocess.TimeoutExpired:
            return {"status": "fail", "returncode": None, "stdout": "", "stderr": f"Timeout > {timeout}s"}
        except Exception as exc:  # pragma: no cover
            return {"status": "fail", "returncode": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


# ── Arithmetic checker (an toàn: chỉ +-*/, không tên/biến/hàm) ──────────────
_ALLOWED = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
)
_EQUATION = re.compile(r"([0-9][0-9.\+\-\*/()\s]{0,40}?)\s*=\s*(-?[0-9]+(?:\.[0-9]+)?)")


def _safe_eval(expr: str) -> float:
    node = ast.parse(expr, mode="eval")
    for n in ast.walk(node):
        if not isinstance(n, _ALLOWED):
            raise ValueError(f"disallowed node: {type(n).__name__}")
    return float(eval(compile(node, "<expr>", "eval"), {"__builtins__": {}}, {}))


def check_arithmetic(text: str) -> List[dict]:
    checks = []
    for expr, claimed in _EQUATION.findall(text or ""):
        expr = expr.strip()
        if not re.search(r"[\+\-\*/]", expr):  # bỏ qua kiểu "x = 5"
            continue
        try:
            val = _safe_eval(expr)
        except Exception:
            continue
        ok = abs(val - float(claimed)) < 1e-6
        detail = f"{expr} = {claimed}" + ("" if ok else f"  (thực tế = {val:g})")
        checks.append({"type": "math", "status": "pass" if ok else "fail", "detail": detail[:300]})
    return checks


def run_verifiers(answer: str, run_code: bool = True, timeout: float = 6.0) -> dict:
    """Chạy mọi kiểm chứng áp dụng được lên một câu trả lời.

    Trả về {status: pass|fail|na, checks: [...], summary: str}.
    """
    checks: List[dict] = []
    if run_code:
        for code in extract_python(answer):
            r = run_python(code, timeout=timeout)
            detail = (r["stderr"].strip() or ("chạy sạch" if r["status"] == "pass" else f"exit {r['returncode']}"))
            checks.append({"type": "python", "status": r["status"], "detail": detail[:300]})
    checks.extend(check_arithmetic(answer))

    if not checks:
        return {"status": "na", "checks": [], "summary": "không có gì để kiểm (không code/số)"}
    n_fail = sum(1 for c in checks if c["status"] == "fail")
    status = "fail" if n_fail else "pass"
    summary = "tất cả qua" if status == "pass" else f"{n_fail}/{len(checks)} kiểm tra FAIL"
    return {"status": status, "checks": checks, "summary": summary}


def evidence_text(evidence: dict) -> str:
    """Định dạng evidence để chèn vào prompt audit / merge."""
    if not evidence or evidence.get("status") == "na":
        return ""
    lines = [f"- [{c['status'].upper()}] {c['type']}: {c['detail']}" for c in evidence["checks"]]
    return "KẾT QUẢ KIỂM CHỨNG THỰC TẾ (chạy code / check số):\n" + "\n".join(lines)
