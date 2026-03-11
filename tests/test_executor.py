import asyncio

import executor
from models import Task


class _FakeProcess:
    returncode = 0

    async def communicate(self):
        return b"", b""

    def kill(self):
        return None


def test_run_claude_uses_configured_model_profile(monkeypatch) -> None:
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProcess()

    monkeypatch.setattr(executor.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(
        executor, "claude_command_args",
        lambda: ["claude", "--model", "claude-opus-4-6", "--effort", "max"],
    )

    ok = asyncio.run(executor._run_claude("hello", "/tmp"))

    assert ok is True
    assert captured["args"][:6] == (
        "claude", "--model", "claude-opus-4-6", "--effort", "max", "-p",
    )


def test_build_executor_prompt_requires_mcp_and_playwright_for_frontend_tasks() -> None:
    task = Task(
        id="dashboard-001",
        title="Dashboard layout",
        description="Implement the dashboard screen from mockup",
        module_id="dashboard",
        files=["templates/dashboard/home.html", "static/css/dashboard.css"],
        forbidden_files=["templates/base.html"],
        branch="factory/dashboard-001",
    )

    prompt = executor.build_executor_prompt(task)

    assert "browser MCP tools" in prompt
    assert "$playwright" in prompt
    assert "mockups" in prompt


def test_build_executor_prompt_includes_lane_prompt_bundle(monkeypatch) -> None:
    monkeypatch.setattr(
        executor,
        "load_lane_prompt_bundle",
        lambda project_dir, lane: "# Lane A2\n- 范围：工作台页面",
    )
    task = Task(
        id="A2-H1",
        title="任务详情",
        description="实现任务详情",
        module_id="A2",
        owner_lane="A2",
        files=["templates/dashboard/task_detail.html"],
        branch="codex/A2-H1",
    )

    prompt = executor.build_executor_prompt(task, "/tmp/project")

    assert "DUERP Lane Instructions" in prompt
    assert "# Lane A2" in prompt
    assert "Never hardcode or commit real API keys" in prompt
