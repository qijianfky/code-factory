import json

from duerp_profile import (
    DUERP_MODULE_OWNED_PATHS,
    _forbidden_for_module,
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
            "targets": ["H2"],
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
            "screen_id": "02",
            "title": "待办中心",
            "lane": "A2",
            "module": "workspace",
            "status": "implemented",
            "mockup": "02-inbox.png",
            "tags": ["inbox"],
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
    assert a2.tasks[0].dependencies == []
    assert "templates/base.html" in a2.tasks[0].forbidden_files
    assert "django-notifications" in a2.tasks[0].description
    assert "EMAIL_HOST" in a2.tasks[0].description


def test_build_duerp_modules_adds_dependency_for_planned_list_screen(tmp_path) -> None:
    docs = tmp_path / "docs" / "parallel"
    prompts = docs / "prompts"
    prompts.mkdir(parents=True)
    (docs / "MASTER_PLAN.md").write_text("# plan")
    (docs / "SCREEN_MANIFEST.json").write_text(json.dumps([
        {
            "screen_id": "02",
            "title": "任务中心",
            "lane": "A2",
            "module": "workspace",
            "status": "planned",
            "mockup": None,
            "tags": ["tasks", "center"],
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
    tasks = {task.id: task for task in a2.tasks}

    assert tasks["A2-H1"].dependencies == ["A2-02"]


def test_build_duerp_modules_adds_cross_module_integration_dependencies(tmp_path) -> None:
    docs = tmp_path / "docs" / "parallel"
    prompts = docs / "prompts"
    prompts.mkdir(parents=True)
    (docs / "MASTER_PLAN.md").write_text("# plan")
    (docs / "KEY_SLOTS.json").write_text(json.dumps([
        {
            "id": "ai",
            "lanes": ["A2"],
            "modules": ["workspace"],
            "targets": ["H8-H10"],
            "env_vars": ["AI_API_KEY", "AI_MODEL"],
            "ui_anchor": "G8 接口管理",
            "settings_anchor": [".env.integrations.example"],
            "notes": "AI provider should stay config-only",
        },
        {
            "id": "travel",
            "lanes": ["A5"],
            "modules": ["oa"],
            "targets": ["24b-24n"],
            "env_vars": ["TRAVEL_APP_ID", "TRAVEL_APP_SECRET"],
            "ui_anchor": "G8 接口管理",
            "settings_anchor": [".env.integrations.example"],
            "notes": "Travel provider should stay config-only",
        },
        {
            "id": "wecom_connect",
            "lanes": ["A8", "A2"],
            "modules": ["integrations", "workspace"],
            "targets": ["H5-H7"],
            "env_vars": ["WECOM_OAUTH_REDIRECT_URI", "WECOM_CALLBACK_TOKEN"],
            "ui_anchor": "G5b 企业微信互通配置",
            "settings_anchor": [".env.integrations.example"],
            "notes": "WeCom deep connect should stay config-only",
        },
    ], ensure_ascii=False))
    (docs / "SCREEN_MANIFEST.json").write_text(json.dumps([
        {
            "screen_id": "H9",
            "title": "AI发文草稿",
            "lane": "A2",
            "module": "workspace",
            "status": "planned",
            "mockup": None,
            "tags": ["dashboard", "ai", "authoring"],
        },
        {
            "screen_id": "24h",
            "title": "订酒店",
            "lane": "A5",
            "module": "oa",
            "status": "planned",
            "mockup": None,
            "tags": ["travel", "booking"],
        },
        {
            "screen_id": "H5",
            "title": "审批待办",
            "lane": "A2",
            "module": "workspace",
            "status": "planned",
            "mockup": None,
            "tags": ["approvals", "todo", "wecom_connect"],
        },
    ], ensure_ascii=False))
    (prompts / "codex-lane-template.md").write_text("# Codex Template")
    (prompts / "claude-lane-template.md").write_text("# Claude Template")
    (prompts / "lane-a2.md").write_text(
        "# Lane A2 — 工作台\n\n"
        "- 范围：工作台页面\n"
        "- owner：A2\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：页面 smoke\n"
    )
    (prompts / "lane-a5.md").write_text(
        "# Lane A5 — OA-HR\n\n"
        "- 范围：OA 与人事页面\n"
        "- owner：A5\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：OA smoke\n"
    )
    (prompts / "lane-a7.md").write_text(
        "# Lane A7 — 设置平台\n\n"
        "- 范围：设置与权限\n"
        "- owner：A7\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：设置 smoke\n"
    )
    (prompts / "lane-a8.md").write_text(
        "# Lane A8 — 集成平台\n\n"
        "- 范围：适配器与渠道\n"
        "- owner：A8\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：集成 smoke\n"
    )

    modules = build_duerp_modules(str(tmp_path))
    order = [module.id for module in modules]
    a2 = next(module for module in modules if module.id == "A2")
    a5 = next(module for module in modules if module.id == "A5")

    assert order.index("A8") < order.index("A2")
    assert next(task for task in a2.tasks if task.id == "A2-H9").dependencies == ["A7-core-001", "A8-101"]
    assert "AI_API_KEY" in next(task for task in a2.tasks if task.id == "A2-H9").description
    assert next(task for task in a2.tasks if task.id == "A2-H5").dependencies == ["A8-104"]
    assert "WECOM_OAUTH_REDIRECT_URI" in next(task for task in a2.tasks if task.id == "A2-H5").description
    assert next(task for task in a5.tasks if task.id == "A5-24h").dependencies == ["A8-102"]
    assert "TRAVEL_APP_ID" in next(task for task in a5.tasks if task.id == "A5-24h").description


def test_build_duerp_modules_keeps_attendance_as_native_erp_flow(tmp_path) -> None:
    docs = tmp_path / "docs" / "parallel"
    prompts = docs / "prompts"
    prompts.mkdir(parents=True)
    (docs / "MASTER_PLAN.md").write_text("# plan")
    (docs / "KEY_SLOTS.json").write_text(json.dumps([], ensure_ascii=False))
    (docs / "SCREEN_MANIFEST.json").write_text(json.dumps([
        {
            "screen_id": "21d",
            "title": "考勤更正申请",
            "lane": "A5",
            "module": "oa",
            "status": "planned",
            "mockup": None,
            "tags": ["oa", "attendance"],
        },
    ], ensure_ascii=False))
    (prompts / "codex-lane-template.md").write_text("# Codex Template")
    (prompts / "lane-a5.md").write_text(
        "# Lane A5 — OA-HR\n\n"
        "- 范围：OA 与人事页面\n"
        "- owner：A5\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：OA smoke\n"
    )

    modules = build_duerp_modules(str(tmp_path))
    a5 = next(module for module in modules if module.id == "A5")

    assert next(task for task in a5.tasks if task.id == "A5-21d").dependencies == []


def test_build_duerp_modules_splits_core_owned_paths(tmp_path) -> None:
    prompts = tmp_path / "docs" / "parallel" / "prompts"
    prompts.mkdir(parents=True)
    (tmp_path / "docs" / "parallel" / "MASTER_PLAN.md").write_text("# plan")
    (prompts / "codex-lane-template.md").write_text("# Codex Template")
    (prompts / "claude-lane-template.md").write_text("# Claude Template")
    (prompts / "lane-a7.md").write_text(
        "# Lane A7 — 权限系统\n\n"
        "- 范围：权限与设置\n"
        "- owner：A7\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：权限 smoke\n"
    )
    (prompts / "lane-a8.md").write_text(
        "# Lane A8 — 集成平台\n\n"
        "- 范围：集成与适配器\n"
        "- owner：A8\n"
        "- blocked_by：A1\n"
        "- handoff_to：A9\n"
        "- tests：集成 smoke\n"
    )
    (prompts / "lane-a9.md").write_text(
        "# Lane A9 — 回归验证\n\n"
        "- 范围：全链路回归\n"
        "- owner：A9\n"
        "- blocked_by：A8\n"
        "- handoff_to：无\n"
        "- tests：E2E smoke\n"
    )

    modules = {module.id: module for module in build_duerp_modules(str(tmp_path))}

    assert set(modules["A7-core"].owned_paths).isdisjoint(modules["A7"].owned_paths)
    assert set(modules["A8-core"].owned_paths).isdisjoint(modules["A8"].owned_paths)
    assert set(modules["A9"].owned_paths).isdisjoint(DUERP_MODULE_OWNED_PATHS["A4"])
    assert modules["A7-core"].tasks[0].owner_lane == "A7-core"
    assert modules["A8-core"].tasks[0].owner_lane == "A8-core"


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
    assert find_duerp_lane_for_path("templates/components/share_sheet.html") == "A8"
    assert find_duerp_lane_for_path("dashboard/reports.py") == "A6"
    assert find_duerp_lane_for_path("core/permissions/policy.py") == "A7-core"
    assert find_duerp_lane_for_path("core/integrations/registry.py") == "A8-core"
    assert find_duerp_lane_for_path("core/integrations/adapters/tax.py") == "A8"
    assert find_duerp_lane_for_path("sales/tests/test_orders.py") == "A4"
    assert find_duerp_lane_for_path("test/test_phase8_e2e.py") == "A9"


def test_forbidden_paths_respect_more_specific_module_ownership() -> None:
    a8_forbidden = _forbidden_for_module("A8")
    a6_forbidden = _forbidden_for_module("A6")
    a1_forbidden = _forbidden_for_module("A1")
    a2_forbidden = _forbidden_for_module("A2")

    assert "templates/components/" not in a8_forbidden
    assert "dashboard/" not in a6_forbidden
    assert "templates/components/share_sheet.html" in a1_forbidden
    assert "dashboard/reports.py" in a2_forbidden

    # A9 owns test/ and core/inbox/tests/ — other module paths stay forbidden
    a9_forbidden = _forbidden_for_module("A9")
    assert "procurement/" in a9_forbidden
    assert "sales/" in a9_forbidden
    assert "dashboard/" in a9_forbidden
    assert "core/integrations/tests/" in a9_forbidden  # owned by A8, not A9
