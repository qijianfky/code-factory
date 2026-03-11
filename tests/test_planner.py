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
