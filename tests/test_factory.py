import asyncio
from pathlib import Path

import factory
from models import FailureKind, Module, ModuleStatus, Task, TaskKind, TaskStatus


def test_execute_and_review_scope_check_failure_marks_task_failed(monkeypatch) -> None:
    async def fake_run_scope_check(task, project_dir):
        raise RuntimeError("scope checker exploded")

    monkeypatch.setattr(factory, "run_scope_check", fake_run_scope_check)

    task = Task(
        id="sales-001-scope1",
        title="Scope validation: Sales detail",
        description="Check scope",
        module_id="sales",
        kind=TaskKind.SCOPE_CHECK,
        parent_task_id="sales-001",
        discovered_files=["templates/base.html"],
    )
    module = Module(id="sales", name="Sales", phase=1, owned_paths=["sales/"], tasks=[task])

    asyncio.run(
        factory.execute_and_review(
            task,
            "/tmp/project",
            module,
            base_branch="feature/unified-architecture",
            branch_prefix="codex/",
        )
    )

    assert task.status == TaskStatus.FAILED
    assert "scope checker exploded" in task.error
    assert task.failure_kind == FailureKind.SCOPE_CHECK_FAILED


def test_handle_scope_violations_routes_cross_owner_dependency(tmp_path) -> None:
    ownership_dir = tmp_path / "docs" / "parallel"
    ownership_dir.mkdir(parents=True)
    (ownership_dir / "OWNERSHIP.md").write_text(
        "# Ownership\n\n"
        "## 共享文件 Owner\n\n"
        "- `A1`：`templates/base.html`\n"
    )

    original = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
        forbidden_files=["templates/base.html"],
        status=TaskStatus.FAILED,
    )
    scope_task = Task(
        id="sales-001-scope1",
        title="Scope validation: Sales detail",
        description="Implement detail page",
        module_id="sales",
        kind=TaskKind.SCOPE_CHECK,
        status=TaskStatus.MERGED,
        parent_task_id="sales-001",
        scope_round=1,
        review_feedback='{"verdicts": {"templates/base.html": "necessary_other_owner"}}',
    )
    module = Module(
        id="sales",
        name="Sales",
        phase=1,
        owned_paths=["sales/"],
        tasks=[original, scope_task],
    )

    factory.handle_scope_violations(module, str(tmp_path))

    assert original.error == 'owner_handoff_required:["templates/base.html"]'
    assert scope_task.error == original.error
    owner_tasks = [task for task in module.tasks if task.id == "sales-001-owner1-a1"]
    rerun_tasks = [task for task in module.tasks if task.id == "sales-001-rerun1"]

    assert len(owner_tasks) == 1
    assert owner_tasks[0].kind == TaskKind.OWNER_HANDOFF
    assert owner_tasks[0].files == ["templates/base.html"]
    assert owner_tasks[0].owner_lane == "A1"

    assert len(rerun_tasks) == 1
    assert rerun_tasks[0].dependencies == ["sales-001-owner1-a1"]
    assert "templates/base.html" in rerun_tasks[0].forbidden_files


def test_handle_scope_violations_falls_back_to_duerp_lane_for_shared_files(tmp_path) -> None:
    parallel = tmp_path / "docs" / "parallel"
    prompts = parallel / "prompts"
    prompts.mkdir(parents=True)
    (parallel / "MASTER_PLAN.md").write_text("# plan")
    (parallel / "OWNERSHIP.md").write_text("# Ownership\n\n## 共享文件 Owner\n\n")
    (prompts / "claude-lane-template.md").write_text("# Claude Template")
    (prompts / "lane-a8.md").write_text(
        "# Lane A8 — 集成平台\n\n"
        "- 范围：统一适配器\n"
        "- owner：A8\n"
        "- blocked_by：无\n"
        "- handoff_to：A9\n"
        "- tests：适配器健康\n"
    )

    original = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
        forbidden_files=["core/integrations/registry.py"],
    )
    scope_task = Task(
        id="sales-001-scope1",
        title="Scope validation: Sales detail",
        description="Implement detail page",
        module_id="sales",
        kind=TaskKind.SCOPE_CHECK,
        status=TaskStatus.MERGED,
        parent_task_id="sales-001",
        scope_round=1,
        review_feedback='{"verdicts": {"core/integrations/registry.py": "necessary_other_owner"}}',
    )
    module = Module(id="sales", name="Sales", phase=1, owned_paths=["sales/"], tasks=[original, scope_task])

    factory.handle_scope_violations(module, str(tmp_path))

    owner_task = next(task for task in module.tasks if task.id == "sales-001-owner1-a8")
    assert owner_task.owner_lane == "A8"
    assert owner_task.agent_type.value == "claude"


def test_run_module_stops_on_quick_check_failure(monkeypatch) -> None:
    async def fake_execute_and_review(task, project_dir, module, **kwargs):
        task.status = TaskStatus.REVIEWING

    async def fake_merge_sequentially(tasks, project_dir, **kwargs):
        for task in tasks:
            if task.status == TaskStatus.REVIEWING:
                task.status = TaskStatus.MERGED

    captured = {}

    async def fake_quick_check(project_dir, tasks=None):
        captured["task_ids"] = [task.id for task in tasks or []]
        return False, "gate failed"

    async def fail_verify(project_dir, tasks=None):
        raise AssertionError("verify_project should not run after quick-check failure")

    monkeypatch.setattr(factory, "execute_and_review", fake_execute_and_review)
    monkeypatch.setattr(factory, "merge_sequentially", fake_merge_sequentially)
    monkeypatch.setattr(factory, "quick_check", fake_quick_check)
    monkeypatch.setattr(factory, "verify_project", fail_verify)

    task = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
    )
    module = Module(id="sales", name="Sales", phase=1, owned_paths=["sales/"], tasks=[task])

    asyncio.run(
        factory.run_module(
            module,
            "/tmp/project",
            base_branch="feature/unified-architecture",
            branch_prefix="codex/",
        )
    )

    assert module.status == ModuleStatus.FAILED
    assert module.e2e_issues == ["gate failed"]
    assert task.status == TaskStatus.MERGED
    assert task.failure_kind == FailureKind.QUICK_CHECK_FAILED
    assert captured["task_ids"] == ["sales-001"]


def test_normalize_resume_state_retries_failed_work() -> None:
    failed_task = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        status=TaskStatus.FAILED,
        retries=2,
        error="agent crashed",
        branch="codex/sales-001",
        worktree="/tmp/worktree",
        failure_kind=FailureKind.RETRYABLE,
    )
    module = Module(
        id="sales",
        name="Sales",
        phase=1,
        status=ModuleStatus.FAILED,
        tasks=[failed_task],
    )

    factory.normalize_resume_state([module])

    assert module.status == ModuleStatus.PENDING
    assert failed_task.status == TaskStatus.PENDING
    assert failed_task.retries == 0
    assert failed_task.error == ""
    assert failed_task.branch == ""
    assert failed_task.worktree == ""
    assert failed_task.failure_kind == FailureKind.NONE


def test_normalize_resume_state_materializes_scope_followups(tmp_path) -> None:
    original = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
        forbidden_files=["templates/base.html"],
        status=TaskStatus.FAILED,
        error='scope_violation:["templates/base.html"]',
        review_feedback="diff summary",
        failure_kind=FailureKind.SCOPE_VIOLATION,
    )
    module = Module(
        id="sales",
        name="Sales",
        phase=1,
        status=ModuleStatus.FAILED,
        owned_paths=["sales/"],
        tasks=[original],
    )

    ownership_dir = tmp_path / "docs" / "parallel"
    ownership_dir.mkdir(parents=True)
    (ownership_dir / "OWNERSHIP.md").write_text("# Ownership\n\n## 共享文件 Owner\n\n")

    factory.normalize_resume_state([module], str(tmp_path))

    scope_tasks = [task for task in module.tasks if task.kind == TaskKind.SCOPE_CHECK]
    assert len(scope_tasks) == 1
    assert scope_tasks[0].status == TaskStatus.PENDING
    assert original.status == TaskStatus.FAILED
