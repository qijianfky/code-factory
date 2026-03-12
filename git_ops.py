"""Git operations for code factory."""
import asyncio
import shutil
from pathlib import Path

from config import MAIN_BRANCH

_git_write_lock = asyncio.Lock()


async def run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def init_repo(project_dir: str, base_branch: str = MAIN_BRANCH) -> None:
    """Initialize git repo if needed. Refuse to proceed on dirty workdir."""
    path = Path(project_dir)
    if not (path / ".git").exists():
        await run_git(["init"], project_dir)
        await run_git(["checkout", "-b", base_branch], project_dir)
        (path / ".gitkeep").touch()
        await run_git(["add", "."], project_dir)
        await run_git(["commit", "-m", "init: code factory project"], project_dir)
    else:
        # Existing repo: check for uncommitted changes
        rc, status, _ = await run_git(["status", "--porcelain"], project_dir)
        if status.strip():
            dirty_count = len(status.strip().splitlines())
            raise RuntimeError(
                f"Working directory has {dirty_count} uncommitted changes. "
                "Commit or stash them before running code factory.\n"
                "  git stash        # to stash\n"
                "  git add -A && git commit -m 'baseline'  # to commit\n"
                f"Dirty files:\n{status[:500]}"
            )
        await _ensure_base_branch(project_dir, base_branch)


async def _ensure_base_branch(project_dir: str, base_branch: str) -> None:
    """Seed the configured base branch from HEAD when an existing repo does not have it yet."""
    rc, _, _ = await run_git(["rev-parse", "--verify", base_branch], project_dir)
    if rc == 0:
        return

    head_rc, _, head_err = await run_git(["rev-parse", "--verify", "HEAD"], project_dir)
    if head_rc != 0:
        raise RuntimeError(
            f"Repository has no commits to seed base branch '{base_branch}': "
            f"{head_err.strip() or 'HEAD is unavailable'}"
        )

    rc, _, err = await run_git(["branch", base_branch, "HEAD"], project_dir)
    if rc != 0:
        raise RuntimeError(
            f"Failed to create base branch '{base_branch}' from HEAD: "
            f"{err.strip() or 'git branch failed'}"
        )


async def seed_assets(project_dir: str, spec_file: str, mockup_files: list[str]) -> None:
    """Copy spec and mockups into project so worktrees can access them."""
    path = Path(project_dir)
    assets = path / "_assets"

    # Skip if already seeded
    if assets.exists() and any(assets.iterdir()):
        return

    assets.mkdir(exist_ok=True)

    # Copy spec
    shutil.copy2(spec_file, assets / Path(spec_file).name)

    # Copy mockups
    if mockup_files:
        mockups_dir = assets / "mockups"
        mockups_dir.mkdir(exist_ok=True)
        for f in mockup_files:
            shutil.copy2(f, mockups_dir / Path(f).name)

    await run_git(["add", "_assets"], project_dir)
    await run_git(["commit", "-m", "chore: add spec and mockups"], project_dir)


async def create_worktree(project_dir: str, branch: str,
                          base_branch: str = MAIN_BRANCH) -> str:
    """Create a git worktree for isolated agent work."""
    async with _git_write_lock:
        safe_name = branch.replace("/", "-")
        worktree_path = str(Path(project_dir).parent / ".factory-worktrees" / safe_name)
        Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)

        # Clean up if exists from previous failed run
        existing = Path(worktree_path)
        if existing.exists():
            await run_git(["worktree", "remove", worktree_path, "--force"], project_dir)
            await run_git(["branch", "-D", branch], project_dir)

        # Create branch from the configured integration branch.
        rc, _, err = await run_git(["branch", branch, base_branch], project_dir)
        if rc != 0:
            raise RuntimeError(
                f"Failed to create branch '{branch}' from '{base_branch}': "
                f"{err.strip() or 'git branch failed'}"
            )
        rc, out, err = await run_git(["worktree", "add", worktree_path, branch], project_dir)
        if rc != 0:
            raise RuntimeError(f"Failed to create worktree: {err}")
        return worktree_path


async def merge_branch(project_dir: str, branch: str,
                       base_branch: str = MAIN_BRANCH) -> tuple[bool, str]:
    """Merge branch into the configured integration branch. Returns (success, error)."""
    async with _git_write_lock:
        await run_git(["checkout", base_branch], project_dir)

        # Try ff-only first
        rc, out, err = await run_git(["merge", "--ff-only", branch], project_dir)
        if rc == 0:
            return True, ""

        # Fall back to regular merge
        rc, out, err = await run_git(["merge", branch, "-m", f"merge: {branch}"], project_dir)
        if rc == 0:
            return True, ""

        # Merge conflict — abort
        await run_git(["merge", "--abort"], project_dir)
        return False, err


async def cleanup_worktree(project_dir: str, worktree_path: str, branch: str) -> None:
    """Remove worktree and delete branch."""
    async with _git_write_lock:
        await run_git(["worktree", "remove", worktree_path, "--force"], project_dir)
        await run_git(["branch", "-D", branch], project_dir)
