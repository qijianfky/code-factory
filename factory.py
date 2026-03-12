"""Code Factory: phased orchestrator with scope resolution.

Modules run sequentially (phase order). Tasks within a module run in parallel
(execute + review), then merge sequentially.

Out-of-scope file modifications trigger scope validation:
  execute → scope violation → discard worktree → scope_check task → rerun task

Usage:
    python factory.py --spec spec.md --mockups ./mockups --project ./output
    python factory.py --project ./output --resume
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from config import BRANCH_PREFIX, MAIN_BRANCH, MAX_PARALLEL_AGENTS, PROGRESS_FILE
from duerp_profile import (
    agent_type_for_lane,
    find_duerp_lane_for_path,
    resolve_branch_prefix,
    resolve_main_branch,
)
from executor import execute_task
from git_ops import cleanup_worktree, create_worktree, init_repo, merge_branch, seed_assets
from models import (
    AgentType, FailureKind, Module, ModuleStatus, Task, TaskKind, TaskStatus,
    MAX_SCOPE_ROUNDS,
)
from ownership import find_owner_lane, load_ownership
from planner import plan
from reviewer import review_task
from scheduler import get_ready_tasks, module_done, module_stats, overall_stats
from scope_resolver import (
    create_owner_handoff_task, create_rerun_task, create_scope_check_task,
    detect_scope_violation, get_cross_owner_files, run_scope_check,
)
from verifier import quick_check, verify_project


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def save_progress(modules: list[Module], project_dir: str) -> None:
    icons = {
        TaskStatus.MERGED: "✓", TaskStatus.FAILED: "✗",
        TaskStatus.RUNNING: "⟳", TaskStatus.REVIEWING: "⟐",
    }
    mod_icons = {
        ModuleStatus.PASSED: "✓", ModuleStatus.FAILED: "✗",
        ModuleStatus.RUNNING: "⟳", ModuleStatus.VERIFYING: "⟐",
    }
    lines = [f"# Factory Progress — {datetime.now().isoformat()}\n\n"]
    for m in modules:
        mi = mod_icons.get(m.status, "·")
        lines.append(f"{mi} MODULE [{m.id}] {m.name} (phase {m.phase}) — {m.status.value}\n")
        for t in m.tasks:
            kind_tag = f" [{t.kind.value}]" if t.kind != TaskKind.NORMAL else ""
            ti = icons.get(t.status, "  ·")
            lines.append(f"    {ti} [{t.id}]{kind_tag} {t.title} — {t.status.value}\n")
            if t.error:
                lines.append(f"        Error: {t.error}\n")
        if m.e2e_issues:
            lines.append(f"    E2E issues: {m.e2e_issues}\n")
        lines.append("\n")
    (Path(project_dir) / PROGRESS_FILE).write_text("".join(lines))

    # Machine-readable state for resume
    state = []
    for m in modules:
        state.append({
            "id": m.id, "name": m.name, "phase": m.phase,
            "status": m.status.value, "owned_paths": m.owned_paths,
            "tasks": [
                {"id": t.id, "title": t.title, "description": t.description,
                 "module_id": t.module_id, "files": t.files,
                 "forbidden_files": t.forbidden_files,
                 "dependencies": t.dependencies,
                 "agent_type": t.agent_type.value,
                 "kind": t.kind.value,
                 "status": t.status.value, "retries": t.retries,
                 "error": t.error, "review_feedback": t.review_feedback,
                 "failure_kind": t.failure_kind.value,
                 "parent_task_id": t.parent_task_id,
                 "discovered_files": t.discovered_files,
                 "scope_round": t.scope_round,
                 "owner_lane": t.owner_lane}
                for t in m.tasks
            ],
        })
    (Path(project_dir) / "factory_state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
    )


async def execute_and_review(
    task: Task,
    project_dir: str,
    module: Module,
    *,
    base_branch: str,
    branch_prefix: str,
) -> None:
    """Execute + review a task. Detects scope violations.

    For SCOPE_CHECK tasks: runs judgment agent, no worktree.
    For NORMAL/RERUN tasks: execute → scope check → review.
    """
    # --- Scope check tasks: no worktree, just judge ---
    if task.kind == TaskKind.SCOPE_CHECK:
        task.status = TaskStatus.RUNNING
        log(f"    [{task.id}] running scope validation...")
        try:
            verdict = await run_scope_check(task, project_dir)
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            task.failure_kind = FailureKind.SCOPE_CHECK_FAILED
            log(f"    [{task.id}] scope validation FAILED: {exc}")
            return

        task.review_feedback = json.dumps(verdict)
        task.status = TaskStatus.MERGED  # scope checks "complete" directly
        task.failure_kind = FailureKind.NONE
        log(f"    [{task.id}] scope verdict: {verdict.get('verdicts', {})}")
        return

    # --- Normal / Rerun tasks ---
    task.branch = f"{branch_prefix}{task.id}"

    try:
        worktree = await create_worktree(project_dir, task.branch, base_branch=base_branch)
        task.worktree = worktree

        # Execute
        success = await execute_task(task, project_dir, worktree)
        if not success:
            raise RuntimeError(task.error or "Agent returned non-zero")

        # Check scope violation BEFORE review
        out_of_scope, diff_summary = await detect_scope_violation(
            worktree, module.owned_paths, task.files, base_branch=base_branch,
        )

        if out_of_scope:
            log(f"    [{task.id}] SCOPE VIOLATION: {out_of_scope}")
            task.discovered_files = out_of_scope

            if task.scope_round >= MAX_SCOPE_ROUNDS:
                task.status = TaskStatus.FAILED
                task.failure_kind = FailureKind.PLANNING_FAILED
                task.error = (
                    f"planning_failed: {len(out_of_scope)} scope violations "
                    f"after {task.scope_round} rounds: {out_of_scope}"
                )
                log(f"    [{task.id}] PLANNING_FAILED: max scope rounds exceeded")
            else:
                # Mark for scope resolution (factory will create scope_check + rerun)
                task.status = TaskStatus.FAILED
                task.failure_kind = FailureKind.SCOPE_VIOLATION
                task.error = f"scope_violation:{json.dumps(out_of_scope)}"
                task.review_feedback = diff_summary  # preserve for scope check

            # Discard worktree — never merge violated code
            await cleanup_worktree(project_dir, worktree, task.branch)
            task.worktree = ""
            return

        # No scope violation → normal review
        task.status = TaskStatus.REVIEWING
        log(f"    [{task.id}] reviewing...")
        approved, feedback = await review_task(task, worktree, base_branch=base_branch)

        if approved:
            task.status = TaskStatus.REVIEWING  # ready for sequential merge
            task.failure_kind = FailureKind.NONE
            log(f"    [{task.id}] approved, ready to merge")
        else:
            task.review_feedback = feedback
            raise RuntimeError(f"Review rejected: {feedback[:200]}")

    except Exception as e:
        if task.status not in (TaskStatus.FAILED,):
            task.retries += 1
            if task.retries >= task.max_retries:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.failure_kind = _classify_failure(str(e))
                log(f"    [{task.id}] FAILED ({task.retries} retries): {e}")
            else:
                task.status = TaskStatus.PENDING
                task.error = str(e)
                task.failure_kind = _classify_failure(str(e))
                log(f"    [{task.id}] retry {task.retries}: {e}")
        # Cleanup worktree on failure
        if task.worktree:
            try:
                await cleanup_worktree(project_dir, task.worktree, task.branch)
            except Exception as exc:
                log(f"    [{task.id}] worktree cleanup failed: {exc}")
            task.worktree = ""


async def merge_sequentially(tasks: list[Task], project_dir: str, *, base_branch: str) -> None:
    """Merge approved tasks one at a time."""
    for task in tasks:
        if task.status != TaskStatus.REVIEWING:
            continue

        merged, err = await merge_branch(project_dir, task.branch, base_branch=base_branch)
        if merged:
            task.status = TaskStatus.MERGED
            task.failure_kind = FailureKind.NONE
            log(f"    [{task.id}] MERGED")
        else:
            task.status = TaskStatus.PENDING
            task.retries += 1
            task.error = f"Merge conflict: {err[:200]}"
            task.failure_kind = FailureKind.MERGE_CONFLICT
            log(f"    [{task.id}] merge conflict, retry {task.retries}")
            if task.retries >= task.max_retries:
                task.status = TaskStatus.FAILED
                log(f"    [{task.id}] FAILED (merge conflicts exhausted)")

        if task.worktree:
            try:
                await cleanup_worktree(project_dir, task.worktree, task.branch)
            except Exception as exc:
                log(f"    [{task.id}] worktree cleanup failed: {exc}")
            task.worktree = ""


def handle_scope_violations(module: Module, project_dir: str = "") -> None:
    """After a batch, create scope_check tasks for scope violations.

    Also create rerun tasks for completed scope_checks.
    """
    new_tasks: list[Task] = []
    ownership = load_ownership(project_dir) if project_dir else None

    for task in module.tasks:
        # 1. Scope violation detected → create scope_check task
        if (task.status == TaskStatus.FAILED
                and task.error.startswith("scope_violation:")
                and task.scope_round < MAX_SCOPE_ROUNDS):
            out_of_scope_json = task.error[len("scope_violation:"):]
            try:
                out_of_scope = json.loads(out_of_scope_json)
            except json.JSONDecodeError:
                log(f"    [{task.id}] malformed scope_violation payload, skipping")
                continue
            diff_summary = task.review_feedback

            sc_task = create_scope_check_task(task, out_of_scope, diff_summary)
            # Avoid duplicates
            if not any(t.id == sc_task.id for t in module.tasks + new_tasks):
                new_tasks.append(sc_task)
                log(f"    Created scope check: [{sc_task.id}]")

        # 2. Scope check completed → create rerun task
        if (task.kind == TaskKind.SCOPE_CHECK
                and task.status == TaskStatus.MERGED
                and task.review_feedback):
            rerun_id = f"{task.parent_task_id}-rerun{task.scope_round}"
            if not any(t.id == rerun_id for t in module.tasks + new_tasks):
                try:
                    verdict = json.loads(task.review_feedback)
                except json.JSONDecodeError:
                    task.status = TaskStatus.FAILED
                    task.error = "Invalid scope verdict payload"
                    task.failure_kind = FailureKind.SCOPE_CHECK_FAILED
                    log(f"    [{task.id}] invalid scope verdict payload")
                    continue

                # Find the original task to base the rerun on
                original = _find_task(module, task.parent_task_id)
                if original:
                    cross_owner = get_cross_owner_files(verdict)
                    if cross_owner:
                        owner_groups = _group_cross_owner_files(cross_owner, ownership)
                        owner_task_ids: list[str] = []
                        for owner_lane, shared_files in owner_groups.items():
                            owner_agent_type = agent_type_for_lane(owner_lane) if owner_lane else original.agent_type
                            owner_task = create_owner_handoff_task(
                                original, owner_lane, shared_files, owner_agent_type=owner_agent_type,
                            )
                            if owner_task is None:
                                continue
                            owner_task_ids.append(owner_task.id)
                            if not any(
                                    existing.id == owner_task.id
                                    for existing in module.tasks + new_tasks):
                                new_tasks.append(owner_task)
                                log(f"    Created owner handoff: [{owner_task.id}] "
                                    f"(lane={owner_lane or 'unresolved'}, files={owner_task.files})")

                        rerun = create_rerun_task(
                            original,
                            verdict,
                            extra_dependencies=owner_task_ids,
                            extra_forbidden=cross_owner,
                        )
                        if not any(
                                existing.id == rerun.id for existing in module.tasks + new_tasks):
                            new_tasks.append(rerun)
                            log(f"    Created rerun: [{rerun.id}] "
                                f"(blocked_on={owner_task_ids or ['shared follow-up']})")

                        original.status = TaskStatus.FAILED
                        original.failure_kind = FailureKind.OWNER_HANDOFF_REQUIRED
                        original.error = (
                            "owner_handoff_required:" + json.dumps(cross_owner)
                        )
                        task.failure_kind = FailureKind.NONE
                        task.error = original.error
                        log(
                            f"    [{original.id}] OWNER HANDOFF REQUIRED: {cross_owner}"
                        )
                        continue

                    rerun = create_rerun_task(original, verdict)
                    if not any(
                            existing.id == rerun.id for existing in module.tasks + new_tasks):
                        new_tasks.append(rerun)
                        log(f"    Created rerun: [{rerun.id}] "
                            f"(expanded={[f for f in rerun.files if f not in original.files]})")

    module.tasks.extend(new_tasks)


def _find_task(module: Module, task_id: str) -> Task | None:
    """Find a task by ID, checking original and derived tasks."""
    for t in module.tasks:
        if t.id == task_id:
            return t
    return None


def _group_cross_owner_files(files: list[str], ownership) -> dict[str, list[str]]:
    """Group shared files by the lane that owns them."""
    groups: dict[str, list[str]] = {}
    for filepath in files:
        owner_lane = find_owner_lane(filepath, ownership) if ownership else ""
        if not owner_lane:
            owner_lane = find_duerp_lane_for_path(filepath)
        groups.setdefault(owner_lane, []).append(filepath)
    return groups


def _is_retryable_failure(task: Task) -> bool:
    """Determine whether a failed task should be retried on --resume."""
    if task.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.REVIEWING):
        return True
    if task.status != TaskStatus.FAILED:
        return False
    return task.failure_kind in {
        FailureKind.NONE,
        FailureKind.RETRYABLE,
        FailureKind.REVIEW_REJECTED,
        FailureKind.MERGE_CONFLICT,
        FailureKind.SCOPE_CHECK_FAILED,
        FailureKind.DEADLOCK,
    }


def _classify_failure(message: str) -> FailureKind:
    lowered = message.lower()
    if lowered.startswith("review rejected:"):
        return FailureKind.REVIEW_REJECTED
    if "merge conflict" in lowered:
        return FailureKind.MERGE_CONFLICT
    if lowered.startswith("planning_failed:"):
        return FailureKind.PLANNING_FAILED
    return FailureKind.RETRYABLE


def _is_superseded_failure(task: Task) -> bool:
    """Failures that are expected to remain after a successful reroute/rerun."""
    return (
        task.status == TaskStatus.FAILED
        and task.failure_kind in {
            FailureKind.SCOPE_VIOLATION,
            FailureKind.OWNER_HANDOFF_REQUIRED,
        }
    )


def _has_blocking_failures(module: Module) -> bool:
    """Return True when the module still has unresolved failures."""
    return any(
        task.status == TaskStatus.FAILED and not _is_superseded_failure(task)
        for task in module.tasks
    )


def _progress_totals(modules: list[Module]) -> tuple[int, int]:
    """Count effective work items, excluding scope checks and superseded originals."""
    total = sum(
        1
        for module in modules
        for task in module.tasks
        if task.kind != TaskKind.SCOPE_CHECK and not _is_superseded_failure(task)
    )
    merged = sum(
        1
        for module in modules
        for task in module.tasks
        if task.status == TaskStatus.MERGED and task.kind != TaskKind.SCOPE_CHECK
    )
    return total, merged


def normalize_resume_state(modules: list[Module], project_dir: str = "") -> None:
    """Prepare saved state for a resume run."""
    for module in modules:
        handle_scope_violations(module, project_dir)

    for module in modules:
        if module.status != ModuleStatus.PASSED:
            module.status = ModuleStatus.PENDING
            module.e2e_issues = []
        for task in module.tasks:
            task.branch = ""
            task.worktree = ""
            if _is_retryable_failure(task):
                task.status = TaskStatus.PENDING
                task.retries = 0
                task.error = ""
                task.failure_kind = FailureKind.NONE


async def run_module(
    module: Module,
    project_dir: str,
    *,
    base_branch: str,
    branch_prefix: str,
    upstream_completed_ids: set[str] | None = None,
) -> None:
    """Run all tasks in a module, then E2E gate."""
    module.status = ModuleStatus.RUNNING
    is_foundation = module.phase == 0
    max_parallel = 1 if is_foundation else MAX_PARALLEL_AGENTS

    log(f"\n  Module [{module.id}] — {module.name} ({len(module.tasks)} tasks, "
        f"{'sequential' if is_foundation else f'parallel max={max_parallel}'})")

    iteration = 0
    while not module_done(module):
        iteration += 1
        stats = module_stats(module)
        log(f"    --- iteration {iteration} | {stats} ---")

        ready = get_ready_tasks(module.tasks, max_parallel, completed_ids=upstream_completed_ids)
        if not ready:
            # Before declaring deadlock, check for pending scope resolution
            handle_scope_violations(module, project_dir)
            ready = get_ready_tasks(module.tasks, max_parallel, completed_ids=upstream_completed_ids)
            if not ready:
                pending = [t for t in module.tasks if t.status == TaskStatus.PENDING]
                if pending:
                    log(f"    DEADLOCK in module [{module.id}]")
                    for t in pending:
                        t.status = TaskStatus.FAILED
                        t.error = "Deadlock"
                        t.failure_kind = FailureKind.DEADLOCK
                break

        log(f"    Executing: {[t.id for t in ready]}")

        if is_foundation:
            for task in ready:
                await execute_and_review(
                    task, project_dir, module, base_branch=base_branch, branch_prefix=branch_prefix,
                )
                if task.status == TaskStatus.REVIEWING:
                    await merge_sequentially([task], project_dir, base_branch=base_branch)
        else:
            await asyncio.gather(*[
                execute_and_review(
                    t, project_dir, module, base_branch=base_branch, branch_prefix=branch_prefix,
                )
                for t in ready
            ])
            await merge_sequentially(ready, project_dir, base_branch=base_branch)

        # Quick check after merges
        merged_tasks = [t for t in ready if t.status == TaskStatus.MERGED]
        merged_count = len(merged_tasks)
        if merged_count > 0:
            ok, err = await quick_check(project_dir, merged_tasks)
            if not ok:
                log(f"    QUICK CHECK FAILED: {err[:200]}")
                module.status = ModuleStatus.FAILED
                module.e2e_issues = [err]
                for task in merged_tasks:
                    task.failure_kind = FailureKind.QUICK_CHECK_FAILED
                log(f"  Module [{module.id}] stopped after quick-check failure")
                return

        # Handle scope violations → create scope_check / rerun tasks
        handle_scope_violations(module, project_dir)

    # E2E gate
    module.status = ModuleStatus.VERIFYING
    merged = sum(1 for t in module.tasks if t.status == TaskStatus.MERGED
                 and t.kind != TaskKind.SCOPE_CHECK)
    failed = sum(1 for t in module.tasks if t.status == TaskStatus.FAILED)
    log(f"  Module [{module.id}] tasks done: {merged} merged, {failed} failed")

    if _has_blocking_failures(module):
        module.status = ModuleStatus.FAILED
        blocking = [t.id for t in module.tasks if t.status == TaskStatus.FAILED and not _is_superseded_failure(t)]
        log(f"  Module [{module.id}] FAILED — unresolved task failures: {blocking}")
        return

    if merged > 0:
        log(f"  E2E gate for [{module.id}]...")
        passed, issues = await verify_project(project_dir, module.tasks)
        if passed:
            module.status = ModuleStatus.PASSED
            log(f"  Module [{module.id}] E2E PASSED")
        else:
            module.e2e_issues = issues
            module.status = ModuleStatus.FAILED
            log(f"  Module [{module.id}] E2E FAILED: {issues}")
            log(f"  Pipeline stopped. Fix issues and run with --resume.")
    else:
        module.status = ModuleStatus.FAILED
        log(f"  Module [{module.id}] FAILED — no tasks merged")


def load_state(project_dir: str) -> list[Module] | None:
    """Load saved state for resume."""
    state_file = Path(project_dir) / "factory_state.json"
    if not state_file.exists():
        return None

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, KeyError) as e:
        log(f"Corrupted state file: {e}. Delete {state_file} and re-run.")
        return None
    modules = []
    for m in state:
        tasks = [
            Task(
                id=t["id"], title=t["title"], description=t["description"],
                module_id=t.get("module_id", ""), files=t.get("files", []),
                forbidden_files=t.get("forbidden_files", []),
                dependencies=t.get("dependencies", []),
                agent_type=AgentType(t.get("agent_type", "claude")),
                kind=TaskKind(t.get("kind", "normal")),
                status=TaskStatus(t["status"]), retries=t.get("retries", 0),
                error=t.get("error", ""),
                review_feedback=t.get("review_feedback", ""),
                failure_kind=FailureKind(t.get("failure_kind", "none")),
                parent_task_id=t.get("parent_task_id", ""),
                discovered_files=t.get("discovered_files", []),
                scope_round=t.get("scope_round", 0),
                owner_lane=t.get("owner_lane", ""),
            )
            for t in m["tasks"]
        ]
        modules.append(Module(
            id=m["id"], name=m["name"], phase=m["phase"],
            owned_paths=m.get("owned_paths", []),
            tasks=tasks, status=ModuleStatus(m["status"]),
        ))
    return modules


def _merged_task_ids(modules: list[Module]) -> set[str]:
    return {
        task.id
        for module in modules
        for task in module.tasks
        if task.status == TaskStatus.MERGED
    }


async def run_factory(spec_file: str, mockup_dir: str, project_dir: str,
                      resume: bool = False) -> None:
    project_path = Path(project_dir).resolve()
    project_dir = str(project_path)
    project_path.mkdir(parents=True, exist_ok=True)
    base_branch = resolve_main_branch(project_dir, MAIN_BRANCH)
    branch_prefix = resolve_branch_prefix(project_dir, BRANCH_PREFIX)

    if resume:
        modules = load_state(project_dir)
        if not modules:
            log("No saved state found. Run without --resume first.")
            sys.exit(1)
        log(f"Resuming from saved state: {len(modules)} modules")
        normalize_resume_state(modules, project_dir)
    else:
        mockup_files = []
        if mockup_dir:
            mockup_files = [
                str(f) for f in Path(mockup_dir).glob("*")
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
            ]

        log(f"Spec: {spec_file}")
        log(f"Mockups: {len(mockup_files)} files")
        log(f"Project: {project_dir}")
        log(f"Base branch: {base_branch}")
        log(f"Branch prefix: {branch_prefix}")

        await init_repo(project_dir, base_branch=base_branch)
        await seed_assets(project_dir, spec_file, mockup_files)

        log("=" * 60)
        log("PLANNING")
        log("=" * 60)
        modules = await plan(spec_file, mockup_files, project_dir)

    total_tasks = sum(len(m.tasks) for m in modules)
    log(f"Plan: {len(modules)} modules, {total_tasks} tasks")
    for m in modules:
        log(f"  Phase {m.phase}: [{m.id}] {m.name} — {len(m.tasks)} tasks")

    log("=" * 60)
    log("EXECUTION")
    log("=" * 60)

    for index, module in enumerate(modules):
        if module.status == ModuleStatus.PASSED:
            log(f"  Module [{module.id}] already passed, skipping")
            continue
        upstream_completed_ids = _merged_task_ids(modules[:index])
        await run_module(
            module,
            project_dir,
            base_branch=base_branch,
            branch_prefix=branch_prefix,
            upstream_completed_ids=upstream_completed_ids,
        )
        save_progress(modules, project_dir)

        if module.status == ModuleStatus.FAILED:
            log(f"\n  Module [{module.id}] FAILED. Run with --resume to retry.")
            break

    # Final E2E
    all_modules_passed = all(m.status == ModuleStatus.PASSED for m in modules)
    if all_modules_passed:
        log("=" * 60)
        log("FINAL E2E VERIFICATION")
        log("=" * 60)
        passed, issues = await verify_project(project_dir)
        log(f"Final E2E: {'PASSED' if passed else f'ISSUES: {issues}'}")
    else:
        log("=" * 60)
        log("FINAL E2E VERIFICATION")
        log("=" * 60)
        log("Skipped final E2E because the pipeline has unresolved module failures.")

    # Summary
    stats = overall_stats(modules)
    real_tasks, real_merged = _progress_totals(modules)
    log("=" * 60)
    log(f"DONE | {real_merged}/{real_tasks} tasks merged | {stats}")
    for m in modules:
        ms = module_stats(m)
        log(f"  [{m.id}] {m.status.value} — {ms}")
    log("=" * 60)

    save_progress(modules, project_dir)

    if real_merged < real_tasks:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Code Factory (phased + scope resolution)")
    parser.add_argument("--spec", default="", help="Spec/requirements file")
    parser.add_argument("--mockups", default="", help="Mockup images directory")
    parser.add_argument("--project", required=True, help="Target project directory")
    parser.add_argument("--resume", action="store_true", help="Resume from saved state")
    args = parser.parse_args()

    if not args.resume and not args.spec:
        parser.error("--spec is required for fresh runs (use --resume to continue)")

    asyncio.run(run_factory(args.spec, args.mockups, args.project, args.resume))


if __name__ == "__main__":
    main()
