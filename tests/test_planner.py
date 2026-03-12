import asyncio

import pytest

import planner
from models import Module
from planner import _validate_ownership


def test_validate_ownership_rejects_nested_paths() -> None:
    plan = {
        "modules": [
            {"id": "foundation", "owned_paths": ["templates/"]},
            {"id": "sales", "owned_paths": ["templates/base.html"]},
        ],
    }

    with pytest.raises(ValueError, match="overlaps"):
        _validate_ownership(plan)


def test_validate_ownership_allows_disjoint_paths() -> None:
    plan = {
        "modules": [
            {"id": "foundation", "owned_paths": ["templates/base.html"]},
            {"id": "sales", "owned_paths": ["sales/", "templates/sales/"]},
        ],
    }

    _validate_ownership(plan)


def test_plan_uses_duerp_profile_without_spawning_agent(tmp_path, monkeypatch) -> None:
    docs = tmp_path / "docs" / "parallel"
    docs.mkdir(parents=True)
    (docs / "MASTER_PLAN.md").write_text("# plan")

    modules = [Module(id="A1", name="壳层", phase=0)]
    monkeypatch.setattr(planner, "build_duerp_modules", lambda project_dir: modules)

    result = asyncio.run(planner.plan("", [], str(tmp_path)))

    assert result == modules
    assert (tmp_path / "factory_plan.json").exists()


def test_plan_falls_back_to_factory_plan_file_when_stdout_is_not_json(tmp_path, monkeypatch) -> None:
    (tmp_path / "factory_plan.json").write_text(
        """{
  "modules": [
    {
      "id": "foundation",
      "name": "Base Foundation",
      "phase": 0,
      "owned_paths": ["templates/base.html"],
      "tasks": []
    }
  ]
}"""
    )

    monkeypatch.setattr(planner, "is_duerp_project", lambda project_dir: False)

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                b"Plan written to `factory_plan.json`.\n\nAnalysis complete.",
                b"",
            )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(planner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(planner.plan("", [], str(tmp_path)))

    assert [module.id for module in result] == ["foundation"]
