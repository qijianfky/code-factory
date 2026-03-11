import config


def test_claude_command_args_include_model_and_effort(monkeypatch) -> None:
    monkeypatch.setattr(config, "CLAUDE_CMD", "claude")
    monkeypatch.setattr(config, "CLAUDE_MODEL", "claude-opus-4-6")
    monkeypatch.setattr(config, "CLAUDE_EFFORT", "max")

    assert config.claude_command_args() == [
        "claude", "--model", "claude-opus-4-6", "--effort", "max",
    ]


def test_codex_command_args_include_model(monkeypatch) -> None:
    monkeypatch.setattr(config, "_codex_cache", ("codex", ["codex"]))
    monkeypatch.setattr(config, "CODEX_MODEL", "gpt5.4ehigh")

    assert config.codex_command_args() == ["codex", "-m", "gpt5.4ehigh"]
