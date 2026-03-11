import asyncio

import pytest

import scope_resolver
from models import Task


class _FakeProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self._stdout = stdout.encode()
        self._stderr = stderr.encode()
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        return None


def test_detect_scope_violation_uses_configured_base_branch(monkeypatch) -> None:
    commands = []

    async def fake_run_git(args, cwd):
        commands.append(args)
        if args[:2] == ["diff", "--name-only"]:
            return 0, "sales/views.py\ntemplates/base.html\n", ""
        if args[:2] == ["diff", "--stat"]:
            return 0, " 2 files changed", ""
        return 0, "", ""

    monkeypatch.setattr(scope_resolver, "run_git", fake_run_git)

    out_of_scope, diff_summary = asyncio.run(
        scope_resolver.detect_scope_violation(
            "/tmp/worktree",
            owned_paths=["sales/"],
            task_files=["sales/views.py"],
            base_branch="feature/unified-architecture",
        )
    )

    assert commands[0] == ["diff", "--name-only", "feature/unified-architecture...HEAD"]
    assert commands[1] == ["diff", "--stat", "feature/unified-architecture...HEAD"]
    assert out_of_scope == ["templates/base.html"]
    assert diff_summary == " 2 files changed"


def test_create_rerun_task_keeps_cross_owner_files_out_of_scope() -> None:
    task = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
        forbidden_files=["templates/base.html"],
    )

    rerun = scope_resolver.create_rerun_task(
        task,
        {"verdicts": {"templates/base.html": "necessary_other_owner"}},
        extra_dependencies=["sales-001-owner1"],
        extra_forbidden=["templates/base.html"],
    )

    assert rerun.files == ["sales/views.py"]
    assert rerun.dependencies == ["sales-001-owner1"]
    assert "templates/base.html" in rerun.forbidden_files


def test_run_scope_check_raises_on_invalid_output(monkeypatch) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess("not json at all")

    monkeypatch.setattr(
        scope_resolver.asyncio, "create_subprocess_exec", fake_create_subprocess_exec,
    )

    task = Task(
        id="sales-001-scope1",
        title="Scope validation: Sales detail",
        description="Check scope",
        module_id="sales",
        parent_task_id="sales-001",
        discovered_files=["templates/base.html"],
        review_feedback="diff summary",
    )

    with pytest.raises(RuntimeError, match="Could not parse scope validation output"):
        asyncio.run(scope_resolver.run_scope_check(task, "/tmp/project"))
