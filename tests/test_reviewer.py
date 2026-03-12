import asyncio

import reviewer
from models import AgentType, Task


class _FakeProcess:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self._stdout = stdout.encode()
        self._stderr = stderr.encode()
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        return None


def test_codex_review_uses_configured_base_branch(monkeypatch) -> None:
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProcess('{"approved": true, "feedback": "ok"}')

    monkeypatch.setattr(reviewer.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(
        reviewer, "codex_command_args", lambda: ["codex", "-c", 'model_reasoning_effort="xhigh"']
    )

    task = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
        forbidden_files=["templates/base.html"],
        agent_type=AgentType.CLAUDE,
    )

    approved, feedback = asyncio.run(
        reviewer._review_with_codex(task, "/tmp", "feature/unified-architecture")
    )

    assert approved is True
    assert feedback == "ok"
    assert captured["args"][:5] == (
        "codex", "-c", 'model_reasoning_effort="xhigh"', "exec", "-s",
    )
    assert captured["args"][5] == "read-only"
    assert "git diff feature/unified-architecture...HEAD" in captured["args"][6]


def test_codex_review_surfaces_stderr_when_agent_fails(monkeypatch) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess("", returncode=1, stderr="boom")

    monkeypatch.setattr(reviewer.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(reviewer, "codex_command_args", lambda: ["codex"])

    task = Task(
        id="sales-001",
        title="Sales detail",
        description="Implement detail page",
        module_id="sales",
        files=["sales/views.py"],
        forbidden_files=["templates/base.html"],
        agent_type=AgentType.CLAUDE,
    )

    approved, feedback = asyncio.run(
        reviewer._review_with_codex(task, "/tmp", "feature/unified-architecture")
    )

    assert approved is False
    assert "boom" in feedback
