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

Every simulation also writes simc's self-contained HTML report and, when
EPHEMR_API_KEY is set, publishes it to https://ephemr.io (ephemeral static
hosting, links expire after 72h) so the full interactive report can be shared
as a link alongside the distilled text summary.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Literal

from tools import tool
from tools.market.blizzard import oauth_token

MAX_OUTPUT_CHARS = 4000
EPHEMR_API_URL = "https://ephemr.io/api/v1/pages"
EPHEMR_MAX_HTML_BYTES = 10 * 1024 * 1024  # free-account upload cap

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


def _publish_ephemr(html_path: Path, title: str) -> str:
    """Publish an HTML report to ephemr.io and return a URL/notice line.

    Returns an empty string when publishing is skipped (no API key, no file,
    oversized file) so callers can simply append the result.
    """
    key = os.getenv("EPHEMR_API_KEY")
    if not key:
        return ""
    if not html_path.exists():
        return ""
    raw = html_path.read_bytes()
    if len(raw) > EPHEMR_MAX_HTML_BYTES:
        return "\n(html report too large for ephemr — skipped)"

    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("html", raw.decode("utf-8", "replace")), ("title", title)):
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    body = ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8")
    request = urllib.request.Request(
        EPHEMR_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.loads(response.read().decode("utf-8"))
        return (
            f"\n\nFull HTML report (public link, expires in 72h): {page['url']}"
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        return f"\n(ephemr publish failed: HTTP {exc.code} {detail})"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"\n(ephemr publish failed: {exc})"


def _profile_title(profile: str) -> str:
    """Best-effort report title: the profile's character name, if any."""
    match = re.search(r'^\s*character="([^"]+)"', profile, re.MULTILINE)
    return f"simc report — {match.group(1)}" if match else "simc report"


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


def _summarize_json(path: Path, elapsed: float) -> str:
    """Turn simc's JSON report into a compact mean/SE table per profileset."""
    report = json.loads(path.read_text(encoding="utf-8"))
    lines = [f"simc json report, finished in {elapsed:.1f}s"]
    sim = report.get("sim", {})
    for player in sim.get("players", []):
        name = player.get("name", "?")
        collected = player.get("collected_data", {})
        dps = collected.get("dps", {})
        mean = dps.get("mean")
        if mean is None:
            continue
        se = dps.get("mean_std_err", dps.get("error", 0)) or 0
        line = f"  {name}: {mean:.0f} dps (SE {se:.0f}, min {dps.get('min', 0):.0f}, max {dps.get('max', 0):.0f})"
        # Scale factors, when calculated, come as lists per stat.
        weights = collected.get("scale_factors", {}) or {}
        if weights:
            line += " | weights: " + ", ".join(
                f"{k}={v:.2f}" for k, v in weights.items() if isinstance(v, (int, float))
            )
        lines.append(line)
    if len(lines) == 1:  # no players parsed
        lines.append("(no player results found in json report)")
    text = "\n".join(lines)
    return text[:MAX_OUTPUT_CHARS]


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
    json_output: bool = False,
    extra_options: list[str] | None = None,
    timeout: int = 900,
) -> str:
    """Run a SimulationCraft simulation on a character profile and return the DPS results. `profile` is the full text of a /simc addon export (starts with lines like `character="Name"`, `level=`, `spec=`) or any simc profile; it may contain multiple characters or `profileset.` blocks to compare gear/talent variants. iterations=0 lets simc choose a smart sample size; higher = slower but more accurate. Set scale_factors=true for stat weights (much slower). Set json_output=true for structured results with mean AND standard error per profile (recommended when comparing variants — feed the means/SEs into the python tool for significance testing: z = delta / sqrt(SE_a^2 + SE_b^2)). Use extra_options for raw simc options, e.g. ["max_time=400", "ptr=1"]."""
    with tempfile.TemporaryDirectory(prefix="simc-") as tmp:
        profile_path = Path(tmp) / "profile.simc"
        profile_path.write_text(profile, encoding="utf-8")

        options = _common_options(
            fight_style, iterations, threads, scale_factors, extra_options
        )
        # Profileset dumps print a full report per set; only the ranking is needed.
        if re.search(r"^\s*profileset\.", profile, re.MULTILINE):
            options.append("profileset_report_details=0")

        json_path: Path | None = None
        if json_output:
            json_path = Path(tmp) / "report.json"
            options.append(f"output={json_path}")
        html_path = Path(tmp) / "report.html"
        options.append(f"html={html_path}")

        cmd = [_simc_binary(), str(profile_path), *options]
        started = time.monotonic()
        proc = _run(cmd, min(timeout, 3600))
        link = _publish_ephemr(html_path, _profile_title(profile))

    if json_output and json_path and json_path.exists():
        return _summarize_json(json_path, time.monotonic() - started) + link

    return (
        _distill(proc.stdout, proc.stderr, proc.returncode, time.monotonic() - started)
        + link
    )


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
    """Run a SimulationCraft simulation on a character imported from the Blizzard armory, e.g. region "us", realm "stormrage", character "Coffee". Fetches a Blizzard API token with BLIZZARD_CLIENT_ID/SECRET (the same free develop.battle.net credentials the realm tools use) and passes it to simc via apitoken=. Prefer simc_simulate with a /simc addon export when available — it is more reliable than armory import."""
    options = _common_options(
        fight_style, iterations, threads, scale_factors, extra_options
    )

    # Armory downloads need Blizzard API credentials. Recent simc removed the
    # apisecret option and its built-in shared key no longer works, so fetch
    # a client-credentials token ourselves (the same working path the realm
    # and progression tools use) and hand it to simc via apitoken=.
    try:
        options.append(f"apitoken={oauth_token()}")
    except RuntimeError as exc:
        return (
            f"Armory authorization unavailable: {exc}. "
            "Use simc_simulate with a /simc addon export instead."
        )

    # simc parses options sequentially and armory= downloads the character
    # the moment it is parsed — apitoken= must come BEFORE armory=.
    options.append(f"armory={region},{realm.strip()},{character.strip()}")

    with tempfile.TemporaryDirectory(prefix="simc-") as tmp:
        html_path = Path(tmp) / "report.html"
        options.append(f"html={html_path}")

        cmd = [_simc_binary(), *options]
        started = time.monotonic()
        proc = _run(cmd, min(timeout, 3600))
        link = _publish_ephemr(html_path, f"simc report — {character.strip()}")

    result = _distill(
        proc.stdout, proc.stderr, proc.returncode, time.monotonic() - started
    ) + link
    if "Unable to authorize" in proc.stdout or "Unable to fetch bearer" in proc.stdout:
        result += (
            "\n\nArmory authorization failed. Use simc_simulate with a "
            "/simc addon export instead."
        )
    return result
