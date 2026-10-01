"""Sandboxed Python execution tool — the agent's calculator and stats workbench.

Runs generated code in a `python -I` subprocess with a wall-clock timeout,
memory/CPU rlimits, and no network access (code is self-generated, so the
threat model is accidents, not adversaries). stdout/stderr are returned, so
`print()` is the way to report results.

numpy and scipy are available — use them for statistics (z-scores, Theil-Sen
slopes, autocorrelation, HHI, Kelly sizing) instead of doing arithmetic by
hand over many-digit copper values.
"""

import resource
import subprocess
import sys
import tempfile
from pathlib import Path

from tools import tool

MAX_OUTPUT_CHARS = 8000
MAX_TIMEOUT_SECONDS = 120
# OpenBLAS (behind numpy/scipy) reserves large virtual address space, so this
# cap is deliberately generous — it stops runaway allocation, not big imports.
MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024


def _limits():
    """Preexec_fn: cap address space and CPU seconds for the child process."""
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_TIMEOUT_SECONDS,) * 2)


@tool
def python(code: str, timeout: int = 20) -> str:
    """Execute Python code and return everything it prints to stdout/stderr. numpy and scipy are available. Use this for ALL arithmetic and statistics — copper/gold conversions, price z-scores, profit projections, comparing sim results — instead of mental math. print() your results. No network access; code runs in a fresh process each call, so imports must be repeated."""
    timeout = max(1, min(timeout, MAX_TIMEOUT_SECONDS))

    with tempfile.TemporaryDirectory(prefix="pyrun-") as tmp:
        script = Path(tmp) / "snippet.py"
        script.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=_limits,
            )
        except subprocess.TimeoutExpired:
            return f"Error: code timed out after {timeout}s"

    out = (proc.stdout or "").rstrip()
    err = (proc.stderr or "").rstrip()
    text = out
    if err:
        text += ("\n" if text else "") + f"stderr:\n{err}"
    if not text:
        text = f"(no output, exit code {proc.returncode})"
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
    return text
