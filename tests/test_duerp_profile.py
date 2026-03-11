import json

from duerp_profile import (
    build_duerp_modules,
    find_duerp_lane_for_path,
    load_lane_prompt_bundle,
    resolve_task_scoped_pytest_targets,
)
from models import Task


def test_build_duerp_modules_uses_manifest_and_skips_implemented(tmp_path) -> None:
    docs = tmp_path / "docs" / "parallel"
    prompts = docs / "prompts"
    prompts.mkdir(parents=True)
    (docs / "MASTER_PLAN.md").write_text("# plan")
    (docs / "OSS_MODULES.json").write_text(json.dumps([
        {
            "id": "notifications",
            "name": "django-notifications",
            "package": "django-notifications-hq",
            "repo": "https://github.com/django-notifications/django-notifications",
            "kind": "python",
            "license": "BSD-3-Clause",
            "stars": 1945,
            "lanes": ["A2"],
            "modules": ["workspace"],
            "targets": ["H1"],
            "why": "通知中心复用通知模型",
            "integration_points": ["notifications/"],
        },
    ], ensure_ascii=False))
    (docs / "KEY_SLOTS.json").write_text(json.dumps([
        {
            "id": "email",
            "lanes": ["A2"],
            "modules": ["workspace"],
            "targets": ["H1"],
            "env_vars": ["EMAIL_HOST", "EMAIL_HOST_PASSWORD"],
            "ui_anchor": "G5 通知配置",
            "settings_anchor": [".env.integrations.example"],
            "notes": "不要提交真实邮箱密码",
        },
    ], ensure_ascii=False))
    (docs / "SCREEN_MANIFEST.json").write_text(json.dumps([
        {
            "screen_id": "01",
            "title": "驾驶舱",
            "lane": "A2",
            "module": "workspace",
            "status": "implemented",
            "mockup": "01-home-hq-leader.png",
            "tags": ["dashboard"],
        },
        {
            "screen_id": "H1",
            "title": "任务详情",
            "lane": "A2",
            "module": "workspace",
            "status": "planned",
            "mockup": None,
            "tags": ["tasks"],
        },
    ], ensure_ascii=False))
    (prompts / "codex-lane-template.md").write_text("# Codex Template")
    (prompts / "lane-a2.md").write_text(
        "# Lane A2 — 工作台\n\n"
        "- 范围：工作台页面\n"
        "- owner：A2\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：页面 smoke\n"
    )

    modules = build_duerp_modules(str(tmp_path))
    a2 = next(module for module in modules if module.id == "A2")

    assert [task.id for task in a2.tasks] == ["A2-H1"]
    assert "templates/base.html" in a2.tasks[0].forbidden_files
    assert "django-notifications" in a2.tasks[0].description
    assert "EMAIL_HOST" in a2.tasks[0].description


def test_load_lane_prompt_bundle_combines_template_and_lane_prompt(tmp_path) -> None:
    prompts = tmp_path / "docs" / "parallel" / "prompts"
    prompts.mkdir(parents=True)
    (tmp_path / "docs" / "parallel" / "MASTER_PLAN.md").write_text("# plan")
    (prompts / "codex-lane-template.md").write_text("template instructions")
    (prompts / "lane-a2.md").write_text(
        "# Lane A2 — 工作台\n\n"
        "- 范围：工作台页面\n"
        "- owner：A2\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：页面 smoke\n"
    )

    bundle = load_lane_prompt_bundle(str(tmp_path), "A2")

    assert "template instructions" in bundle
    assert "# Lane A2" in bundle


def test_resolve_task_scoped_pytest_targets_uses_lane_mapping(tmp_path) -> None:
    (tmp_path / "docs" / "parallel").mkdir(parents=True)
    (tmp_path / "docs" / "parallel" / "MASTER_PLAN.md").write_text("# plan")

    targets = resolve_task_scoped_pytest_targets(str(tmp_path), [
        Task(
            id="A4-B1",
            title="库存台账",
            description="实现库存台账 screen",
            module_id="A4",
            owner_lane="A4",
            files=["templates/warehouse/ledger.html"],
        ),
    ])

    assert "sales/tests" in targets
    assert "warehouse/tests" in targets
    assert "test/test_run19_frontend.py" in targets


def test_find_duerp_lane_for_path_uses_owned_paths() -> None:
    assert find_duerp_lane_for_path("templates/base.html") == "A1"
    assert find_duerp_lane_for_path("core/integrations/registry.py") == "A8"
