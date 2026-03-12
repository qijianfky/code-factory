"""Planner: spec + mockups → phased module plan with file ownership."""
import asyncio
import json
import re
from pathlib import Path

from config import AGENT_TIMEOUT, agent_env, claude_command_args, PROTECTED_FILES
from duerp_profile import build_duerp_modules, is_duerp_project
from models import AgentType, Module, Task

PLANNER_PROMPT = """You are a project planner for a code factory working on an EXISTING Django codebase.

## Your Job
1. Explore the existing project structure (run `find . -type f -name "*.py" | head -100`, read key models.py, views.py, urls.py)
2. Read the spec and mockup images in `_assets/`
3. Identify what's ALREADY implemented vs what's MISSING
4. Output a PHASED module plan as JSON with FILE OWNERSHIP

## File Ownership Rules (CRITICAL)
- Each module MUST declare `owned_paths`: the files/directories ONLY it may modify
- Tasks within a module may ONLY touch files in their module's `owned_paths`
- NO two modules may own the same file — if they conflict, create a shared dependency in Phase 0
- Foundation (Phase 0) owns shared files: base templates, shared models, URL root config
- The following files are PROTECTED and NO module may modify them:
{protected_files}

## Architecture Rules
- Phase 0 = FOUNDATION: shared components ALL modules depend on. Tasks run SEQUENTIALLY.
  - base templates, sidebar, header, context panel
  - shared models (User, Role, Permission, Organization)
  - URL routing framework, settings
- Phase 1+ = BUSINESS MODULES: one module per business domain. Tasks within run in PARALLEL.
- Within a module, set task dependencies correctly (models before views, views before templates)
- Assign agent: "claude" for UI/templates/complex views with mockups, "codex" for models/API/tests

## Output Format — ONLY output this JSON:
```json
{{
  "modules": [
    {{
      "id": "foundation",
      "name": "Base Foundation",
      "phase": 0,
      "owned_paths": ["templates/base.html", "templates/components/", "core/models.py", "erp/urls.py"],
      "tasks": [
        {{
          "id": "foundation-001",
          "title": "Base template with three-column layout",
          "description": "Implement... See _assets/mockups/01-home-hq-leader.png. Acceptance: ...",
          "files": ["templates/base.html", "static/css/base.css"],
          "dependencies": [],
          "agent_type": "claude"
        }}
      ]
    }},
    {{
      "id": "procurement",
      "name": "Procurement Module",
      "phase": 1,
      "owned_paths": ["procurement/", "templates/procurement/"],
      "tasks": [...]
    }}
  ]
}}
```

## Critical Rules
- Task IDs prefixed with module ID (e.g. "procurement-001")
- Dependencies ONLY within same module (cross-module handled by phase order)
- Reference mockup images in descriptions
- Do NOT create tasks for already-working features
- `owned_paths` must not overlap between modules
""".format(protected_files="\n".join(f"  - {p}" for p in PROTECTED_FILES))


async def plan(spec_file: str, mockup_files: list[str], project_dir: str) -> list[Module]:
    """Call Claude Code to generate phased module plan."""
    if is_duerp_project(project_dir):
        modules = build_duerp_modules(project_dir)
        _validate_modules(_serialize_modules(modules))
        (Path(project_dir) / "factory_plan.json").write_text(
            json.dumps(_serialize_modules(modules), indent=2, ensure_ascii=False),
        )
        return modules

    env = agent_env()

    proc = await asyncio.create_subprocess_exec(
        *claude_command_args(), "-p", PLANNER_PROMPT, "--dangerously-skip-permissions",
        cwd=project_dir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Planner timed out")

    if proc.returncode != 0:
        raise RuntimeError(f"Planner failed: {stderr.decode()[:500]}")

    raw = stdout.decode()
    plan_path = Path(project_dir) / "factory_plan.json"
    try:
        plan_data = _extract_json_object(raw)
    except ValueError as exc:
        plan_data = _load_plan_from_file(plan_path, exc)

    # Validate: no overlapping owned_paths
    _validate_ownership(plan_data)
    _validate_modules(plan_data)

    # Save full plan
    (Path(project_dir) / "factory_plan.json").write_text(
        json.dumps(plan_data, indent=2, ensure_ascii=False),
    )

    modules = []
    for m in plan_data["modules"]:
        owned = m.get("owned_paths", [])
        tasks = [
            Task(
                id=t["id"],
                title=t["title"],
                description=t["description"],
                module_id=m["id"],
                files=t.get("files", []),
                forbidden_files=_compute_forbidden(owned, plan_data["modules"], m["id"]),
                dependencies=t.get("dependencies", []),
                agent_type=_safe_agent_type(t.get("agent_type", "claude")),
            )
            for t in m.get("tasks", [])
        ]
        modules.append(Module(
            id=m["id"],
            name=m["name"],
            phase=m["phase"],
            owned_paths=owned,
            tasks=tasks,
        ))

    modules.sort(key=lambda mod: mod.phase)
    return modules


def _load_plan_from_file(plan_path: Path, parse_error: ValueError) -> dict:
    """Load planner output from disk when the agent writes a plan file directly."""
    if not plan_path.exists():
        raise parse_error

    try:
        obj = json.loads(plan_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not extract JSON from planner output and {plan_path.name} was invalid JSON"
        ) from exc

    if not isinstance(obj, dict) or "modules" not in obj:
        raise ValueError(
            f"Could not extract JSON from planner output and {plan_path.name} did not contain a modules object"
        )
    return obj


def _serialize_modules(modules: list[Module]) -> dict:
    """Convert modules/tasks to the saved planner schema."""
    return {
        "modules": [
            {
                "id": module.id,
                "name": module.name,
                "phase": module.phase,
                "owned_paths": module.owned_paths,
                "tasks": [
                    {
                        "id": task.id,
                        "title": task.title,
                        "description": task.description,
                        "files": task.files,
                        "dependencies": task.dependencies,
                        "agent_type": task.agent_type.value,
                        "owner_lane": task.owner_lane,
                    }
                    for task in module.tasks
                ],
            }
            for module in modules
        ]
    }


def _safe_agent_type(value: str) -> AgentType:
    """Convert string to AgentType, defaulting to CLAUDE on invalid input."""
    try:
        return AgentType(value)
    except ValueError:
        return AgentType.CLAUDE


def _compute_forbidden(owned: list[str], all_modules: list[dict], my_id: str) -> list[str]:
    """Compute files this module must NOT touch (other modules' owned_paths + protected)."""
    forbidden = list(PROTECTED_FILES)
    for m in all_modules:
        if m["id"] == my_id:
            continue
        forbidden.extend(m.get("owned_paths", []))
    return forbidden


def _validate_ownership(plan_data: dict) -> None:
    """Check no two modules claim the same path."""
    seen: list[tuple[str, str]] = []
    for m in plan_data.get("modules", []):
        for path in m.get("owned_paths", []):
            normalized = _normalize_owned_path(path)
            for claimed_path, owner in seen:
                if _paths_overlap(normalized, claimed_path):
                    raise ValueError(
                        f"Ownership conflict: '{path}' claimed by [{m['id']}] "
                        f"overlaps with '{claimed_path}' owned by [{owner}]"
                    )
            seen.append((normalized, m["id"]))


def _validate_modules(plan_data: dict) -> None:
    """Validate task IDs and global task dependencies."""
    seen_task_ids: set[str] = set()

    for module in plan_data.get("modules", []):
        for task in module.get("tasks", []):
            task_id = task["id"]
            if task_id in seen_task_ids:
                raise ValueError(f"Duplicate task id: {task_id}")
            seen_task_ids.add(task_id)

    for module in plan_data.get("modules", []):
        for task in module.get("tasks", []):
            task_id = task["id"]
            for dep in task.get("dependencies", []):
                if dep == task_id:
                    raise ValueError(f"Task [{task_id}] cannot depend on itself")
                if dep not in seen_task_ids:
                    raise ValueError(
                        f"Task [{task_id}] in module [{module['id']}] depends on unknown "
                        f"task [{dep}]"
                    )


def _normalize_owned_path(path: str) -> str:
    """Normalize ownership paths so overlap checks are stable."""
    normalized = Path(path).as_posix().lstrip("./")
    if not normalized:
        return normalized
    if path.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _paths_overlap(left: str, right: str) -> bool:
    """Check exact and nested ownership overlap."""
    if left == right:
        return True
    left_prefix = left if left.endswith("/") else f"{left}/"
    right_prefix = right if right.endswith("/") else f"{right}/"
    return left.startswith(right_prefix) or right.startswith(left_prefix)


def _extract_json_object(text: str) -> dict:
    """Extract JSON object with modules key from agent output."""
    try:
        wrapper = json.loads(text)
        if isinstance(wrapper, dict) and "result" in wrapper:
            text = wrapper["result"]
        elif isinstance(wrapper, dict) and "modules" in wrapper:
            return wrapper
    except json.JSONDecodeError:
        pass

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        obj = json.loads(match.group(1))
        if isinstance(obj, dict):
            return obj

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])

    raise ValueError(f"Could not extract JSON from planner output: {text[:300]}")
