"""Configuration for code factory."""
import os
import shutil
import subprocess


MAX_PARALLEL_AGENTS = 5
AGENT_TIMEOUT = 900  # 15 minutes per task
MAX_RETRIES = 3

MAIN_BRANCH = os.getenv("CODE_FACTORY_MAIN_BRANCH", "feature/unified-architecture")
BRANCH_PREFIX = os.getenv("CODE_FACTORY_BRANCH_PREFIX", "codex/")

CLAUDE_CMD = "claude"
CLAUDE_MODEL = os.getenv("CODE_FACTORY_CLAUDE_MODEL", "claude-opus-4-6")
CLAUDE_EFFORT = os.getenv("CODE_FACTORY_CLAUDE_EFFORT", "max")
CODEX_MODEL = os.getenv("CODE_FACTORY_CODEX_MODEL", "")
CODEX_EFFORT = os.getenv("CODE_FACTORY_CODEX_EFFORT", "xhigh")

TASK_FILE = "task_list.json"
PROGRESS_FILE = "factory-progress.txt"

# Protected files that NO task agent may modify
PROTECTED_FILES = [
    "manage.py",
    "requirements/*.txt",
    "pyproject.toml",
    ".gitignore",
    "CLAUDE.md",
    "AGENTS.md",
    "_assets/**",
    "factory_plan.json",
    "factory_state.json",
]

# Quality gate commands (run in order, ALL must pass)
# Override by placing a factory_gates.json in the project root
DEFAULT_GATE_COMMANDS = [
    ["python", "manage.py", "check"],
    ["python", "manage.py", "makemigrations", "--check", "--dry-run"],
]

AGENTS_GATE_SECTION = "构建 & 测试"


def detect_codex() -> tuple[str, list[str]]:
    """Detect available Codex CLI. Returns (cmd, base_args).

    Tries in order:
    1. codex (direct binary)
    2. npx @openai/codex (npm package)
    3. None (Codex unavailable, fall back to Claude for all tasks)
    """
    # Direct binary
    if shutil.which("codex"):
        # Verify it's the OpenAI one, not the static site generator
        try:
            result = subprocess.run(
                ["codex", "exec", "--help"],
                capture_output=True, text=True, timeout=10,
            )
            if "non-interactively" in result.stdout.lower() or result.returncode == 0:
                return "codex", ["codex"]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # npx
    if shutil.which("npx"):
        try:
            result = subprocess.run(
                ["npx", "@openai/codex", "exec", "--help"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return "npx", ["npx", "@openai/codex"]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return "", []


_codex_cache: tuple[str, list[str]] | None = None


def _get_codex() -> tuple[str, list[str]]:
    global _codex_cache
    if _codex_cache is None:
        _codex_cache = detect_codex()
    return _codex_cache


def codex_available() -> bool:
    """Check if Codex CLI is available (lazy, no subprocess at import time)."""
    return bool(_get_codex()[0])


def agent_env() -> dict[str, str]:
    """Environment for spawned agent subprocesses (filters CLAUDECODE)."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}


def claude_command_args() -> list[str]:
    """Return Claude CLI args with the configured model profile."""
    args = [CLAUDE_CMD]
    if CLAUDE_MODEL:
        args.extend(["--model", CLAUDE_MODEL])
    if CLAUDE_EFFORT:
        args.extend(["--effort", CLAUDE_EFFORT])
    return args


def codex_command_args() -> list[str]:
    """Return Codex CLI args with the configured model profile."""
    args = list(_get_codex()[1])
    if CODEX_MODEL:
        args.extend(["-m", CODEX_MODEL])
    if CODEX_EFFORT:
        args.extend(["-c", f'model_reasoning_effort="{CODEX_EFFORT}"'])
    return args
