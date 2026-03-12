import asyncio
from pathlib import Path

import git_ops


def test_init_repo_creates_missing_base_branch_for_existing_repo(tmp_path, monkeypatch) -> None:
    commands = []

    async def fake_run_git(args, cwd):
        commands.append((args, cwd))
        if args == ["status", "--porcelain"]:
            return 0, "", ""
        if args == ["rev-parse", "--verify", "feature/unified-architecture"]:
            return 1, "", "fatal: Needed a single revision"
        if args == ["rev-parse", "--verify", "HEAD"]:
            return 0, "abc123\n", ""
        if args == ["branch", "feature/unified-architecture", "HEAD"]:
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(git_ops, "run_git", fake_run_git)

    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()

    asyncio.run(git_ops.init_repo(str(project_dir), "feature/unified-architecture"))

    assert any(
        args == ["branch", "feature/unified-architecture", "HEAD"]
        for args, _ in commands
    )


def test_create_worktree_uses_configured_base_branch(tmp_path, monkeypatch) -> None:
    commands = []

    async def fake_run_git(args, cwd):
        commands.append((args, cwd))
        return 0, "", ""

    monkeypatch.setattr(git_ops, "run_git", fake_run_git)

    project_dir = tmp_path / "repo"
    project_dir.mkdir()

    worktree = asyncio.run(
        git_ops.create_worktree(
            str(project_dir), "codex/sales-001", base_branch="feature/unified-architecture",
        )
    )

    assert worktree.endswith(".factory-worktrees/codex-sales-001")
    assert any(
        args == ["branch", "codex/sales-001", "feature/unified-architecture"]
        for args, _ in commands
    )


def test_create_worktree_reports_branch_creation_failure(tmp_path, monkeypatch) -> None:
    async def fake_run_git(args, cwd):
        if args == ["branch", "codex/sales-001", "feature/unified-architecture"]:
            return 128, "", "fatal: not a valid object name feature/unified-architecture"
        return 0, "", ""

    monkeypatch.setattr(git_ops, "run_git", fake_run_git)

    project_dir = tmp_path / "repo"
    project_dir.mkdir()

    try:
        asyncio.run(
            git_ops.create_worktree(
                str(project_dir), "codex/sales-001", base_branch="feature/unified-architecture",
            )
        )
    except RuntimeError as exc:
        assert "Failed to create branch 'codex/sales-001'" in str(exc)
    else:
        raise AssertionError("create_worktree should fail when base branch is invalid")


def test_merge_branch_checks_out_configured_base_branch(monkeypatch) -> None:
    commands = []

    async def fake_run_git(args, cwd):
        commands.append((args, cwd))
        if args[:2] == ["merge", "--ff-only"]:
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(git_ops, "run_git", fake_run_git)

    merged, err = asyncio.run(
        git_ops.merge_branch("/tmp/project", "codex/sales-001", "feature/unified-architecture")
    )

    assert merged is True
    assert err == ""
    assert commands[0][0] == ["checkout", "feature/unified-architecture"]
