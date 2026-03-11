from models import Task
from verifier import _load_agents_gate_commands, load_gate_commands


def test_load_agents_gate_commands_uses_activation_preamble(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "## 构建 & 测试\n\n"
        "```bash\n"
        "source ./venv/bin/activate\n"
        "python manage.py check\n"
        "python scripts/check_compliance.py\n"
        "pre-commit run --all-files\n"
        "```\n"
    )

    commands = _load_agents_gate_commands(str(tmp_path))

    assert commands == [
        "source ./venv/bin/activate && python manage.py check",
        "source ./venv/bin/activate && python scripts/check_compliance.py",
        "source ./venv/bin/activate && pre-commit run --all-files",
    ]


def test_load_agents_gate_commands_supports_quality_gate_heading(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "## 质量门禁\n\n"
        "```bash\n"
        "source ./venv/bin/activate\n"
        "python manage.py check\n"
        "python scripts/check_layers.py\n"
        "```\n"
    )

    commands = _load_agents_gate_commands(str(tmp_path))

    assert commands == [
        "source ./venv/bin/activate && python manage.py check",
        "source ./venv/bin/activate && python scripts/check_layers.py",
    ]


def test_load_gate_commands_prefers_agents_over_defaults(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "## 构建 & 测试\n\n"
        "```bash\n"
        "python manage.py check\n"
        "python scripts/check_layers.py\n"
        "```\n"
    )

    commands = load_gate_commands(str(tmp_path))

    assert commands == [
        "python manage.py check",
        "python scripts/check_layers.py",
    ]


def test_load_gate_commands_rewrites_pytest_for_duerp_tasks(tmp_path) -> None:
    parallel = tmp_path / "docs" / "parallel"
    prompts = parallel / "prompts"
    prompts.mkdir(parents=True)
    (parallel / "MASTER_PLAN.md").write_text("# plan")
    (tmp_path / "AGENTS.md").write_text(
        "## 构建 & 测试\n\n"
        "```bash\n"
        "source ./venv/bin/activate\n"
        "python manage.py check\n"
        "python -m pytest test/ -q\n"
        "python scripts/check_layers.py\n"
        "```\n"
    )

    commands = load_gate_commands(str(tmp_path), [
        Task(id="A4-B1", title="库存台账", description="screen", owner_lane="A4"),
    ])

    assert commands[0] == "source ./venv/bin/activate && python manage.py check"
    assert "python -m pytest sales/tests warehouse/tests" in commands[1]
    assert "--tb=short" in commands[1]
