"""Execute tasks by spawning Claude Code or Codex with ownership constraints."""
import asyncio

from config import AGENT_TIMEOUT, agent_env, claude_command_args, codex_available, codex_command_args
from duerp_profile import load_lane_prompt_bundle
from models import AgentType, Task, TaskStatus

PLAYWRIGHT_SKILL_PATH = "/Users/invincible_bigtoilet/.codex/skills/playwright/SKILL.md"

EXECUTOR_PROMPT = """You are implementing a specific task in an existing Django project.

## Task
ID: {task_id}
Title: {task_title}

## Description
{task_description}

## Files you MAY create/modify
{task_files}

## Files you MUST NOT modify (owned by other modules or protected)
{forbidden_files}

## Owner lane
{owner_lane}

{lane_prompt_bundle}

## Rules
- You are on branch `{branch}`. Implement the task completely.
- Read `_assets/` for spec and mockup images if you need design context.
- EXPLORE existing code first: read related models, views, templates, URLs.
- Follow the project's existing patterns (model style, template structure, URL naming).
- If the task touches integrations or settings, prefer the approved OSS candidates already listed in the task context.
- Never hardcode or commit real API keys, passwords, or tokens. Only add placeholders in `.env.example`, `.env.integrations.example`, or documented key slots.
- Write tests if the task involves backend logic.
- Run `python manage.py check` before committing.
- Commit your changes with a descriptive message when done.
- NEVER modify files in the forbidden list. If you need changes there, note it in your commit message.

{frontend_guidance}

{review_feedback}
"""


async def execute_task(task: Task, project_dir: str, worktree_path: str) -> bool:
    """Execute a single task. Returns True on success."""
    task.status = TaskStatus.RUNNING

    prompt = build_executor_prompt(task, project_dir)

    try:
        if task.agent_type == AgentType.CODEX and codex_available():
            return await _run_codex(prompt, worktree_path)
        else:
            # Fall back to Claude if Codex unavailable
            return await _run_claude(prompt, worktree_path)
    except asyncio.TimeoutError:
        task.error = "Agent timed out"
        return False
    except Exception as e:
        task.error = str(e)
        return False


def build_executor_prompt(task: Task, project_dir: str = "") -> str:
    """Build the executor prompt for a task."""
    feedback = ""
    if task.review_feedback:
        feedback = f"## Review Feedback (MUST address)\n{task.review_feedback}"

    forbidden_str = "\n".join(f"- {f}" for f in task.forbidden_files) if task.forbidden_files else "(none)"
    lane = task.owner_lane or task.module_id.split("-")[0]
    lane_prompt_bundle = ""
    if project_dir:
        bundle = load_lane_prompt_bundle(project_dir, lane)
        if bundle:
            lane_prompt_bundle = (
                "## DUERP Lane Instructions (MANDATORY)\n"
                f"{bundle}"
            )

    return EXECUTOR_PROMPT.format(
        task_id=task.id,
        task_title=task.title,
        task_description=task.description,
        task_files="\n".join(f"- {f}" for f in task.files) or "(decide based on description)",
        forbidden_files=forbidden_str,
        owner_lane=task.owner_lane or "(current module owner)",
        lane_prompt_bundle=lane_prompt_bundle,
        branch=task.branch,
        frontend_guidance=_frontend_guidance(task),
        review_feedback=feedback,
    )


def _frontend_guidance(task: Task) -> str:
    """Extra instructions for UI-heavy tasks."""
    if not _is_frontend_task(task):
        return ""

    return (
        "## Frontend Design Workflow (MANDATORY for this task)\n"
        "- This is a frontend/design task. You MUST use the available browser MCP tools "
        "(Playwright/Chrome) for visual validation.\n"
        f"- Use the [$playwright]({PLAYWRIGHT_SKILL_PATH}) skill workflow when the runtime "
        "supports skills.\n"
        "- Open the relevant page locally in a real browser, take a fresh snapshot, interact "
        "through the UI, and re-snapshot after major DOM changes.\n"
        "- Compare the rendered page against `_assets/mockups/` when mockups exist.\n"
        "- Capture a screenshot after the layout is implemented or adjusted.\n"
        "- Do not treat frontend work as complete until the browser pass matches the intended "
        "structure and interactions.\n"
    )


def _is_frontend_task(task: Task) -> bool:
    """Detect tasks that should use browser MCP + frontend skill workflow."""
    file_markers = (
        "static/", ".css", ".js", ".ts", ".tsx", ".jsx",
    )
    text_markers = (
        "frontend", "ui", "ux", "layout", "page", "screen", "mockup",
        "design", "alpine", "tailwind", "htmx",
    )
    file_haystacks = [filepath.lower() for filepath in task.files]
    text_haystacks = [task.title.lower(), task.description.lower()]
    return (
        any(marker in haystack for haystack in file_haystacks for marker in file_markers)
        or any(marker in haystack for haystack in text_haystacks for marker in text_markers)
    )


async def _run_claude(prompt: str, cwd: str) -> bool:
    """Spawn Claude Code CLI."""
    env = agent_env()

    proc = await asyncio.create_subprocess_exec(
        *claude_command_args(), "-p", prompt, "--dangerously-skip-permissions",
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise

    return proc.returncode == 0


async def _run_codex(prompt: str, cwd: str) -> bool:
    """Spawn Codex CLI (auto-detected command)."""
    proc = await asyncio.create_subprocess_exec(
        *codex_command_args(), "exec", "-s", "workspace-write", prompt,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise

    return proc.returncode == 0
