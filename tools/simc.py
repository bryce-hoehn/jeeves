"""SimulationCraft CLI tools — WoW combat simulations.

Drives the `simc` command-line executable
(https://github.com/simulationcraft/simc). The binary is located via the
SIMC_PATH env var or PATH; simulations run as a subprocess and the text
report (stdout) is distilled into the tail summary tables so replies fit in
Discord messages.

Typical input for `simc_simulate` is a /simc addon export: the multiline dump
starting with `character="Name"` / `spec=` / `level=` lines. SimC is not
bundled — install it (or build it on Linux) and set SIMC_PATH if it is not on
PATH.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal

from tools import tool

MAX_OUTPUT_CHARS = 4000

FightStyle = Literal[
    "Patchwerk",
    "LightMovement",
    "HeavyMovement",
    "HecticAddCleave",
    "CleaveAdd",
    "DungeonSlice",
]


def _simc_binary() -> str:
    """Return the path to the simc executable, raising if unavailable."""
    path = os.getenv("SIMC_PATH") or shutil.which("simc")
    if not path:
        raise RuntimeError(
            "simc CLI not found — install SimulationCraft from "
            "https://github.com/simulationcraft/simc or set SIMC_PATH"
        )
    return path


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run simc, raising a clean error on timeout or spawn failure."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=max(1, timeout)
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"simc timed out after {timeout}s") from None
    except FileNotFoundError:
        raise RuntimeError(f"could not execute {_simc_binary()}") from None


def _distill(stdout: str, stderr: str, returncode: int, elapsed: float) -> str:
    """Condense a full simc report into a compact, tail-focused summary."""
    lines = stdout.splitlines()

    # Version banner, e.g. "SimulationCraft 1102-01" — usually the first line.
    version = next((l.strip() for l in lines if "SimulationCraft" in l), "?")

    problems = [
        l.rstrip()
        for l in lines
        if re.match(r"\s*(Error|Warning|Unable to parse)", l)
    ][:8]

    # Multi-actor / profileset runs end with a DPS Ranking table, and scale
    # factor runs end with a Scale Factors table — keep the report tail from
    # whichever section appears; the summary tables live at the end.
    start = next(
        (
            i for i, l in enumerate(lines)
            if "DPS Ranking" in l or l.startswith("Scale Factors")
        ),
        len(lines) - 40,
    )
    body = lines[start:]

    parts = [
        f"simc ({version}) exit {returncode}, finished in {elapsed:.1f}s"
    ]
    if problems:
        parts.append("Issues from report:")
        parts += [f"  {p}" for p in problems]
    parts.extend(l for l in body if l.strip())

    text = "\n".join(parts)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "\n... (report truncated)"
    if stderr.strip():
        text += f"\nstderr: {stderr.strip()[:300]}"
    return text


def _common_options(
    fight_style: str,
    iterations: int,
    threads: int,
    scale_factors: bool,
    extra_options: list[str] | None,
) -> list[str]:
    options = [
        f"fight_style={fight_style}",
        f"iterations={max(0, iterations)}",
    ]
    if threads > 0:
        options.append(f"threads={threads}")
    if scale_factors:
        options += ["calculate_scale_factors=1", "normalize_scale_factors=1"]
    if extra_options:
        options += [o.strip() for o in extra_options if o.strip()]
    return options


@tool
def simc_check() -> str:
    """Check that the simc CLI is installed and report its version. Use this first if unsure whether SimulationCraft is available."""
    binary = _simc_binary()
    proc = _run([binary], timeout=30)
    text = "\n".join(
        l for l in (proc.stdout + proc.stderr).splitlines() if l.strip()
    )[:1500]
    return f"simc executable: {binary}\n{text}"


@tool
def simc_simulate(
    profile: str,
    fight_style: FightStyle = "Patchwerk",
    iterations: int = 10000,
    threads: int = 0,
    scale_factors: bool = False,
    extra_options: list[str] | None = None,
    timeout: int = 900,
) -> str:
    """Run a SimulationCraft simulation on a character profile and return the DPS results. `profile` is the full text of a /simc addon export (starts with lines like `character="Name"`, `level=`, `spec=`) or any simc profile; it may contain multiple characters or `profileset.` blocks to compare gear/talent variants. iterations=0 lets simc choose a smart sample size; higher = slower but more accurate. Set scale_factors=true for stat weights (much slower). Use extra_options for raw simc options, e.g. ["max_time=400", "ptr=1"]."""
    with tempfile.TemporaryDirectory(prefix="simc-") as tmp:
        profile_path = Path(tmp) / "profile.simc"
        profile_path.write_text(profile, encoding="utf-8")

        options = _common_options(
            fight_style, iterations, threads, scale_factors, extra_options
        )
        # Profileset dumps print a full report per set; only the ranking is needed.
        if re.search(r"^\s*profileset\.", profile, re.MULTILINE):
            options.append("profileset_report_details=0")

        cmd = [_simc_binary(), str(profile_path), *options]
        started = time.monotonic()
        proc = _run(cmd, min(timeout, 3600))

    return _distill(proc.stdout, proc.stderr, proc.returncode, time.monotonic() - started)


@tool
def simc_armory_simulate(
    region: Literal["us", "eu", "tw", "kr"],
    realm: str,
    character: str,
    fight_style: FightStyle = "Patchwerk",
    iterations: int = 10000,
    threads: int = 0,
    scale_factors: bool = False,
    extra_options: list[str] | None = None,
    timeout: int = 900,
) -> str:
    """Run a SimulationCraft simulation on a character imported from the Blizzard armory, e.g. region "us", realm "stormrage", character "Coffee". Requires the simc build to have Blizzard API access (official releases do). Prefer simc_simulate with a /simc addon export when available — it is more reliable than armory import."""
    options = _common_options(
        fight_style, iterations, threads, scale_factors, extra_options
    )
    options.append(f"armory={region},{realm.strip()},{character.strip()}")

    cmd = [_simc_binary(), *options]
    started = time.monotonic()
    proc = _run(cmd, min(timeout, 3600))

    return _distill(proc.stdout, proc.stderr, proc.returncode, time.monotonic() - started)
