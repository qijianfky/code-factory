import asyncio
from pathlib import Path

import git_ops


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
