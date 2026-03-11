"""Scope resolution: detect violations, judge necessity, generate rerun tasks."""
import asyncio
import fnmatch
import json
import re

from config import AGENT_TIMEOUT, agent_env, claude_command_args, MAIN_BRANCH
from git_ops import run_git
from models import AgentType, Task, TaskKind, TaskStatus, MAX_SCOPE_ROUNDS


# --- Detection ---

async def detect_scope_violation(
    worktree_path: str,
    owned_paths: list[str],
    task_files: list[str],
    base_branch: str = MAIN_BRANCH,
) -> tuple[list[str], str]:
    """Check if task modified files outside its allowed scope.

    Returns (out_of_scope_files, diff_summary).
    """
    rc, stdout, _ = await run_git(
        ["diff", "--name-only", f"{base_branch}...HEAD"], worktree_path,
    )
    if rc != 0:
        return [], ""

    changed = [f.strip() for f in stdout.splitlines() if f.strip()]
    allowed = set(task_files) | set(owned_paths)

    out_of_scope = [f for f in changed if not _is_allowed(f, allowed)]

    diff_summary = ""
    if out_of_scope:
        rc, stdout, _ = await run_git(
            ["diff", "--stat", f"{base_branch}...HEAD"], worktree_path,
        )
        diff_summary = stdout

    return out_of_scope, diff_summary


def _is_allowed(filepath: str, allowed_patterns: set[str]) -> bool:
    """Check if a file path matches any allowed pattern."""
    for pattern in allowed_patterns:
        # Directory prefix: "procurement/" matches "procurement/models.py"
        if pattern.endswith("/") and filepath.startswith(pattern):
            return True
        # Glob match
        if fnmatch.fnmatch(filepath, pattern):
            return True
        # Exact match
        if filepath == pattern:
            return True
    return False


# --- Scope Check Task ---

SCOPE_CHECK_PROMPT = """You are judging whether out-of-scope file modifications are necessary for a task.

## Original Task
ID: {task_id}
Title: {task_title}
Description:
{task_description}

## Allowed files for this task
{allowed_files}

## Out-of-scope files that were modified
{out_of_scope_files}

## Diff summary
{diff_summary}

## Instructions
For EACH out-of-scope file, judge ONE of:
- "necessary_same_lane": The change is genuinely required and belongs to the same module
- "necessary_other_owner": The change is required but belongs to another module
- "unnecessary": The agent should not have touched this file

Be strict. Only mark "necessary" if the task literally cannot work without this file change.

Output ONLY a JSON object:
```json
{{
  "verdicts": {{
    "path/to/file.py": "necessary_same_lane",
    "other/file.py": "unnecessary"
  }},
  "reasoning": "Brief explanation"
}}
```
"""


def create_scope_check_task(original_task: Task, out_of_scope: list[str],
                            diff_summary: str) -> Task:
    """Create a scope-validation task."""
    return Task(
        id=f"{original_task.id}-scope{original_task.scope_round + 1}",
        title=f"Scope validation: {original_task.title}",
        description=original_task.description,
        module_id=original_task.module_id,
        files=original_task.files,
        kind=TaskKind.SCOPE_CHECK,
        parent_task_id=original_task.id,
        discovered_files=out_of_scope,
        scope_round=original_task.scope_round + 1,
        review_feedback=diff_summary,  # store diff summary for the check prompt
    )


def get_cross_owner_files(verdict: dict) -> list[str]:
    """Return files that require a shared-owner follow-up task."""
    verdicts = verdict.get("verdicts", {})
    return [
        filepath
        for filepath, judgment in verdicts.items()
        if judgment == "necessary_other_owner"
    ]


async def run_scope_check(task: Task, project_dir: str) -> dict:
    """Run the scope validation agent. Returns verdict dict."""
    prompt = SCOPE_CHECK_PROMPT.format(
        task_id=task.parent_task_id,
        task_title=task.title.replace("Scope validation: ", ""),
        task_description=task.description,
        allowed_files="\n".join(f"- {f}" for f in task.files),
        out_of_scope_files="\n".join(f"- {f}" for f in task.discovered_files),
        diff_summary=task.review_feedback or "(no diff available)",
    )

    env = agent_env()

    proc = await asyncio.create_subprocess_exec(
        *claude_command_args(), "-p", prompt, "--dangerously-skip-permissions",
        cwd=project_dir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Scope validation timed out")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Scope validation agent failed: {stderr.decode()[:300]}"
        )

    raw = stdout.decode()

    # Unwrap Claude JSON wrapper
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict) and "result" in wrapper:
            raw = wrapper["result"]
    except json.JSONDecodeError:
        pass

    # Extract verdict JSON (nested object with "verdicts" key)
    # Use multiline search since the JSON might span lines
    for attempt in [
        # Try full object parse
        lambda: json.loads(raw),
        # Try markdown extraction
        lambda: json.loads(re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL).group(1)),
        # Try brace extraction
        lambda: json.loads(raw[raw.find("{"):raw.rfind("}") + 1]),
    ]:
        try:
            obj = attempt()
            if isinstance(obj, dict) and "verdicts" in obj:
                return obj
        except (json.JSONDecodeError, AttributeError, ValueError):
            continue

    raise RuntimeError(
        f"Could not parse scope validation output: {raw[:300]}"
    )


# --- Rerun Task Generation ---

def create_owner_handoff_task(
    original_task: Task,
    owner_lane: str,
    shared_files: list[str],
    *,
    owner_agent_type: AgentType | None = None,
) -> Task | None:
    """Create a follow-up task for required shared files."""
    if not shared_files:
        return None

    scope_round = original_task.scope_round + 1
    shared_notes = "\n".join(f"- {filepath}" for filepath in shared_files)
    owner_suffix = f" {owner_lane}" if owner_lane else ""

    return Task(
        id=f"{original_task.id}-owner{scope_round}{('-' + owner_lane.lower()) if owner_lane else ''}",
        title=f"[Owner Handoff{owner_suffix}] {original_task.title}",
        description=(
            original_task.description + "\n\n"
            "## Shared Ownership Follow-up\n"
            f"Assigned owner lane: {owner_lane or 'unresolved'}\n"
            "Scope review determined the original task requires these shared files:\n"
            f"{shared_notes}\n\n"
            "Implement only the shared-file changes needed to unblock the rerun task."
        ),
        module_id=original_task.module_id,
        files=shared_files,
        forbidden_files=[
            filepath
            for filepath in original_task.forbidden_files
            if filepath not in shared_files
        ],
        dependencies=list(original_task.dependencies),
        kind=TaskKind.OWNER_HANDOFF,
        parent_task_id=original_task.id,
        scope_round=scope_round,
        agent_type=owner_agent_type or original_task.agent_type,
        owner_lane=owner_lane,
    )


def create_rerun_task(original_task: Task, verdict: dict, *,
                      extra_dependencies: list[str] | None = None,
                      extra_forbidden: list[str] | None = None) -> Task:
    """Create a rerun task based on scope validation verdict."""
    verdicts = verdict.get("verdicts", {})
    scope_round = original_task.scope_round + 1

    expanded_files = list(original_task.files)
    accumulated_forbidden = list(extra_forbidden or [])

    for filepath, judgment in verdicts.items():
        if judgment == "necessary_same_lane":
            if filepath not in expanded_files:
                expanded_files.append(filepath)
        elif judgment == "unnecessary" and filepath not in accumulated_forbidden:
            accumulated_forbidden.append(filepath)

    # Build scope adjustment notes
    scope_notes = []
    new_allowed = [f for f in expanded_files if f not in original_task.files]
    if new_allowed:
        scope_notes.append(f"EXPANDED: now allowed to modify {new_allowed}")
    if accumulated_forbidden:
        scope_notes.append(
            f"STRICTLY FORBIDDEN (judged unnecessary in scope review): "
            f"{accumulated_forbidden}. Do NOT touch these files under any circumstances."
        )

    dependencies = list(dict.fromkeys(original_task.dependencies + list(extra_dependencies or [])))

    return Task(
        id=f"{original_task.id}-rerun{scope_round}",
        title=f"[Rerun] {original_task.title}",
        description=(
            original_task.description + "\n\n"
            "## Scope Adjustments (from automated scope review)\n" +
            "\n".join(scope_notes)
        ),
        module_id=original_task.module_id,
        files=expanded_files,
        forbidden_files=list(set(original_task.forbidden_files + accumulated_forbidden)),
        dependencies=dependencies,
        kind=TaskKind.RERUN,
        parent_task_id=original_task.id,
        scope_round=scope_round,
        agent_type=original_task.agent_type,
    )
