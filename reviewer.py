"""Code review agent — fail-safe: reject on any uncertainty."""
import asyncio
import json
import sys

from config import (
    AGENT_TIMEOUT, agent_env, claude_command_args, codex_available,
    codex_command_args, MAIN_BRANCH,
)
from models import AgentType, Task

REVIEW_PROMPT = """You are a code reviewer. Review the changes on this branch.

## Task that was implemented
Title: {task_title}
Description: {task_description}

## Ownership constraints
This task may ONLY modify files in: {allowed_files}
These files are FORBIDDEN: {forbidden_files}

## Instructions
1. Run `git diff {base_branch}...HEAD` to see all changes
2. Check:
   - Does the code implement what the task describes?
   - Did it modify any FORBIDDEN files? (auto-reject if yes)
   - Are there bugs, security issues, or missing edge cases?
   - Does the code follow project conventions?
3. Output ONLY a JSON object:

```json
{{
  "approved": true,
  "feedback": "Looks good."
}}
```

Or if rejected:

```json
{{
  "approved": false,
  "feedback": "Specific issues to fix."
}}
```

IMPORTANT: If in doubt, REJECT. It is better to reject good code than approve bad code.
"""


async def review_task(task: Task, worktree_path: str,
                      base_branch: str = MAIN_BRANCH) -> tuple[bool, str]:
    """Review using adversarial agent. FAIL-SAFE: reject on error."""
    if task.agent_type == AgentType.CLAUDE and codex_available():
        return await _review_with_codex(task, worktree_path, base_branch)
    else:
        if task.agent_type == AgentType.CLAUDE and not codex_available():
            print(
                f"[WARN] [{task.id}] Claude reviews its own code — "
                "no adversarial review (Codex unavailable)",
                file=sys.stderr, flush=True,
            )
        return await _review_with_claude(task, worktree_path, base_branch)


async def _review_with_codex(task: Task, worktree_path: str,
                             base_branch: str) -> tuple[bool, str]:
    """Use Codex review command."""
    review_instructions = (
        f"Task: {task.title}\n"
        f"Description: {task.description}\n\n"
        f"Allowed files: {task.files}\n"
        f"Forbidden files: {task.forbidden_files[:10]}\n\n"
        "Check: does the code implement the task correctly? "
        "Did it modify forbidden files? Are there bugs? "
        "Output JSON: {\"approved\": true/false, \"feedback\": \"...\"}\n"
        "IMPORTANT: If in doubt, REJECT."
    )

    proc = await asyncio.create_subprocess_exec(
        *codex_command_args(), "review", "--base", base_branch, review_instructions,
        cwd=worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return False, "Review timed out — rejecting for safety"

    if proc.returncode != 0:
        return False, "Review agent failed — rejecting for safety"

    return _parse_verdict(stdout.decode())


async def _review_with_claude(task: Task, worktree_path: str,
                              base_branch: str) -> tuple[bool, str]:
    """Use Claude Code for review."""
    prompt = REVIEW_PROMPT.format(
        task_title=task.title,
        task_description=task.description,
        allowed_files=", ".join(task.files) or "(any within module)",
        forbidden_files=", ".join(task.forbidden_files[:10]) or "(none)",
        base_branch=base_branch,
    )

    env = agent_env()

    proc = await asyncio.create_subprocess_exec(
        *claude_command_args(), "-p", prompt, "--dangerously-skip-permissions",
        cwd=worktree_path,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return False, "Review timed out — rejecting for safety"

    if proc.returncode != 0:
        return False, "Review agent failed — rejecting for safety"

    return _parse_verdict(stdout.decode())


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


def _parse_verdict(raw: str) -> tuple[bool, str]:
    """Extract approved/feedback. FAIL-SAFE: reject on parse failure."""
    # Unwrap Claude JSON wrapper
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict) and "result" in wrapper:
            raw = wrapper["result"]
    except json.JSONDecodeError:
        pass

    obj = _extract_json_with_key(raw, "approved")
    if obj is not None:
        return obj.get("approved", False), obj.get("feedback", "No feedback")

    # Could not parse → reject
    return False, f"Could not parse review output — rejecting for safety. Raw: {raw[:200]}"
