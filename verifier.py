"""E2E verification with configurable quality gates. Fail-safe."""
import asyncio
import json
import re
from pathlib import Path

from config import (
    AGENT_TIMEOUT, AGENTS_GATE_SECTION, agent_env, claude_command_args,
    DEFAULT_GATE_COMMANDS,
)
from duerp_profile import resolve_task_scoped_pytest_targets
from models import Task


def _extract_json_with_key(raw: str, key: str) -> dict | None:
    """Extract a JSON object containing the given key, supporting nested braces."""
    idx = raw.find(f'"{key}"')
    if idx == -1:
        return None
    start = raw.rfind('{', 0, idx)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == '{':
            depth += 1
        elif raw[i] == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None

VERIFY_PROMPT = """You are verifying that a Django project runs correctly after code changes.

## Steps
1. Run `python manage.py check` — must pass
2. Run `python manage.py migrate --run-syncdb` — apply migrations
3. Start the dev server: `python manage.py runserver 0.0.0.0:18899 &`
4. Wait 3 seconds for startup
5. Use Playwright MCP (browser_navigate) to open http://localhost:18899
6. Take a screenshot
7. Navigate to 2-3 key pages, screenshot each
8. Kill the dev server

## Output ONLY a JSON object:
```json
{{
  "passed": true/false,
  "issues": ["list of issues found"]
}}
```

IMPORTANT: If ANYTHING fails or looks wrong, set "passed": false.
"""


async def run_gate_commands(project_dir: str, tasks: list[Task] | None = None) -> tuple[bool, list[str]]:
    """Run all quality gate commands. ALL must pass."""
    commands = load_gate_commands(project_dir, tasks)

    issues = []
    for cmd in commands:
        proc, rendered = await _spawn_gate_command(cmd, project_dir)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            issues.append(f"TIMEOUT: {rendered}")
            continue

        if proc.returncode != 0:
            output = stderr.decode()[:300] or stdout.decode()[:300]
            issues.append(f"FAILED: {rendered}\n{output}")

    return len(issues) == 0, issues


async def verify_project(project_dir: str, tasks: list[Task] | None = None) -> tuple[bool, list[str]]:
    """Run quality gates + Playwright E2E. Fail-safe: reject on any error."""
    all_issues = []

    # Step 1: Quality gates
    gates_ok, gate_issues = await run_gate_commands(project_dir, tasks)
    if not gates_ok:
        all_issues.extend(gate_issues)
        # Don't bother with Playwright if basic checks fail
        return False, all_issues

    # Step 2: Playwright E2E via Claude Code
    env = agent_env()

    proc = await asyncio.create_subprocess_exec(
        *claude_command_args(), "-p", VERIFY_PROMPT, "--dangerously-skip-permissions",
        cwd=project_dir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return False, ["E2E verification timed out"]

    if proc.returncode != 0:
        return False, [f"E2E agent failed: {stderr.decode()[:300]}"]

    # Parse result — fail-safe
    raw = stdout.decode()
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict) and "result" in wrapper:
            raw = wrapper["result"]
    except json.JSONDecodeError:
        pass

    obj = _extract_json_with_key(raw, "passed")
    if obj is not None:
        if not obj.get("passed", False):
            all_issues.extend(obj.get("issues", ["E2E reported failure"]))
            return False, all_issues
        return True, []

    # Could not parse → fail
    return False, [f"Could not parse E2E output — failing for safety. Raw: {raw[:200]}"]


async def quick_check(project_dir: str, tasks: list[Task] | None = None) -> tuple[bool, str]:
    """Quick sanity check: run gate commands only (no Playwright)."""
    ok, issues = await run_gate_commands(project_dir, tasks)
    return ok, "\n".join(issues)


def load_gate_commands(project_dir: str, tasks: list[Task] | None = None) -> list[list[str] | str]:
    """Resolve project-specific gates from JSON or AGENTS.md."""
    gate_file = Path(project_dir) / "factory_gates.json"
    if gate_file.exists():
        commands = json.loads(gate_file.read_text())
    else:
        agents_commands = _load_agents_gate_commands(project_dir)
        if agents_commands:
            commands = agents_commands
        else:
            commands = DEFAULT_GATE_COMMANDS

    if tasks:
        commands = _apply_task_scoped_pytest_targets(project_dir, commands, tasks)
    return commands


def _apply_task_scoped_pytest_targets(
    project_dir: str,
    commands: list[list[str] | str],
    tasks: list[Task],
) -> list[list[str] | str]:
    """Replace broad pytest gates with task-scoped DUERP targets when available."""
    targets = resolve_task_scoped_pytest_targets(project_dir, tasks)
    if not targets:
        return commands

    scoped_pytest = f"python -m pytest {' '.join(targets)} -q --tb=short"
    replaced = []
    saw_pytest = False

    for command in commands:
        if isinstance(command, str):
            marker = "python -m pytest"
            idx = command.find(marker)
            if idx == -1:
                replaced.append(command)
                continue
            prefix = command[:idx]
            replaced.append(f"{prefix}{scoped_pytest}")
            saw_pytest = True
            continue

        if command[:3] == ["python", "-m", "pytest"]:
            replaced.append(["python", "-m", "pytest", *targets, "-q", "--tb=short"])
            saw_pytest = True
            continue

        replaced.append(command)

    if not saw_pytest:
        replaced.append(scoped_pytest)

    return replaced


def _load_agents_gate_commands(project_dir: str) -> list[str]:
    """Extract gate commands from AGENTS.md if present."""
    agents_file = Path(project_dir) / "AGENTS.md"
    if not agents_file.exists():
        return []

    text = agents_file.read_text()
    match = None
    for section in (AGENTS_GATE_SECTION, "质量门禁"):
        pattern = rf"##\s+{re.escape(section)}.*?```bash\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            break
    if match is None:
        return []

    lines = [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip()
    ]
    if not lines:
        return []

    preamble = []
    commands = []
    for line in lines:
        if line.startswith("source ") or line.startswith("export "):
            preamble.append(line)
            continue
        commands.append(line)

    if not commands:
        return []

    prefix = " && ".join(preamble)
    if prefix:
        return [f"{prefix} && {command}" for command in commands]
    return commands


async def _spawn_gate_command(
    command: list[str] | str, project_dir: str,
) -> tuple[asyncio.subprocess.Process, str]:
    """Start a gate command, supporting exec arrays and shell strings."""
    if isinstance(command, str):
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", command,
            cwd=project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return proc, command

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=project_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return proc, " ".join(command)
