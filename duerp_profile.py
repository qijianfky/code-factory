"""DUERP-specific profile inputs for planning, prompting, and gates."""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from config import PROTECTED_FILES
from models import AgentType, Module, Task


DUERP_MASTER_PLAN = "docs/parallel/MASTER_PLAN.md"
DUERP_OWNERSHIP = "docs/parallel/OWNERSHIP.md"
DUERP_PROMPTS_DIR = "docs/parallel/prompts"
DUERP_SCREEN_MANIFEST = "docs/parallel/SCREEN_MANIFEST.json"
DUERP_OSS_MODULES = "docs/parallel/OSS_MODULES.json"
DUERP_KEY_SLOTS = "docs/parallel/KEY_SLOTS.json"
DUERP_MAIN_BRANCH = "feature/unified-architecture"
DUERP_BRANCH_PREFIX = "codex/"

DUERP_LANE_PHASES = {
    "A1": 0,
    "A7-core": 0,
    "A8-core": 0,
    "A2": 1,
    "A3": 1,
    "A5": 1,
    "A4": 2,
    "A6": 2,
    "A7": 2,
    "A8": 3,
    "A9": 3,
}

DUERP_LANE_AGENT_TYPES = {
    "A7": AgentType.CLAUDE,
    "A8": AgentType.CLAUDE,
}

DUERP_MODULE_OWNED_PATHS = {
    "A1": [
        "templates/base.html",
        "templates/components/",
        "static/js/stores/",
    ],
    "A7-core": [
        "core/permissions/",
        "core/health/",
    ],
    "A8-core": [
        "core/integration/",
        "core/integrations/registry.py",
        "core/integrations/health.py",
        "core/integrations/feature_gates.py",
        "core/integrations/attachments.py",
    ],
    "A2": [
        "dashboard/",
        "notifications/",
        "templates/dashboard/",
        "templates/inbox/",
        "templates/notifications/",
        "templates/search/",
    ],
    "A3": [
        "procurement/",
        "contracts/",
        "approval/",
        "partners/",
        "templates/procurement/",
        "templates/contracts/",
        "templates/approval/",
        "templates/partners/",
    ],
    "A4": [
        "sales/",
        "warehouse/",
        "templates/sales/",
        "templates/warehouse/",
    ],
    "A5": [
        "oa/",
        "hr/",
        "templates/oa/",
        "templates/hr/",
    ],
    "A6": [
        "finance/",
        "dashboard/reports.py",
        "templates/finance/",
        "templates/reports/",
    ],
    "A7": [
        "accounts/",
        "org/",
        "projects/",
        "templates/settings/",
        "templates/projects/",
        "templates/system/",
        "templates/org/",
    ],
    "A8": [
        "core/integrations/adapters/",
        "core/integrations/providers/",
        "core/integrations/channels/",
        "core/integrations/tests/",
        "templates/components/share_sheet.html",
    ],
    "A9": [
        "test/",
        "core/inbox/tests/",
    ],
}

DUERP_MODULE_FILE_HINTS = {
    "workspace": [
        "dashboard/",
        "notifications/",
        "templates/dashboard/",
        "templates/inbox/",
        "templates/notifications/",
        "templates/search/",
    ],
    "procurement": ["procurement/", "templates/procurement/"],
    "contracts": ["contracts/", "templates/contracts/"],
    "approvals": ["approval/", "templates/approval/"],
    "hr": ["hr/", "templates/hr/"],
    "oa": ["oa/", "templates/oa/"],
    "schedule": ["oa/", "hr/", "templates/oa/", "templates/hr/"],
    "sales": ["sales/", "templates/sales/"],
    "partners": ["partners/", "templates/partners/"],
    "warehouse": ["warehouse/", "templates/warehouse/"],
    "finance": ["finance/", "templates/finance/"],
    "reports": ["finance/", "dashboard/reports.py", "templates/finance/", "templates/reports/"],
    "projects": ["projects/", "templates/projects/"],
    "settings": ["accounts/", "org/", "templates/settings/"],
    "system_health": ["templates/system/"],
}

DUERP_LANE_TEST_TARGETS = {
    "A1": [
        "dashboard/tests",
        "core/inbox/tests",
        "test/test_view_smoke.py",
        "test/test_run19_frontend.py",
    ],
    "A2": [
        "dashboard/tests",
        "core/inbox/tests",
        "notifications/tests",
        "test/test_view_smoke.py",
        "test/test_run19_frontend.py",
    ],
    "A3": [
        "procurement/tests",
        "contracts/tests",
        "approval/tests",
        "partners/tests",
        "test/test_e2e_supply_chain.py",
        "test/test_view_smoke.py",
    ],
    "A4": [
        "sales/tests",
        "warehouse/tests",
        "test/test_e2e_supply_chain.py",
        "test/test_run22_warehouse_coverage.py",
        "test/test_view_smoke.py",
    ],
    "A5": [
        "oa/tests",
        "hr/tests",
        "test/test_view_smoke.py",
    ],
    "A6": [
        "finance/tests",
        "dashboard/tests",
        "notifications/tests",
        "test/test_run20_reports.py",
        "test/test_view_smoke.py",
    ],
    "A7": [
        "accounts/tests",
        "org/tests",
        "projects/tests",
        "core/permissions/tests",
        "core/tests",
        "test/test_view_smoke.py",
    ],
    "A8": [
        "core/integrations/tests",
        "notifications/tests",
        "test/test_run18_integration.py",
        "test/test_run21_device_integration.py",
    ],
    "A9": [
        "test/test_view_smoke.py",
        "test/test_run19_frontend.py",
        "test/test_phase8_e2e.py",
        "test/test_e2e_supply_chain.py",
        "test/test_api_contract.py",
    ],
}

DUERP_STATIC_TASKS = {
    "A1": [
        {
            "id": "A1-001",
            "title": "冻结壳层与共享组件契约",
            "description": "根据 docs/parallel/MASTER_PLAN.md 和 lane-a1 prompt 冻结三栏壳层、导航、IdentityBar、ContextPanel、共享组件接口。",
        },
        {
            "id": "A1-002",
            "title": "统一前端视觉验证基线",
            "description": "建立桌面/窄屏视觉检查基线，并确保前端任务都以浏览器 MCP + mockup 校验收口。",
        },
    ],
    "A7-core": [
        {
            "id": "A7-core-001",
            "title": "冻结权限与设置配置契约",
            "description": "先完成角色、权限、系统参数、接口管理与系统健康 UI 的共享配置契约，再放行业务 lane 消费。",
        },
    ],
    "A8-core": [
        {
            "id": "A8-core-001",
            "title": "冻结适配器注册与 feature gate",
            "description": "先完成适配器注册表、统一健康聚合、feature gate、附件接口和分享/通知渠道契约。",
        },
    ],
    "A8": [
        {
            "id": "A8-101",
            "title": "实现 AI/OCR/对象存储适配器",
            "description": "接通 openclaw、ocr、minio 三类适配器，并为页面入口提供真实门控。",
        },
        {
            "id": "A8-102",
            "title": "实现税务/物流/通知渠道适配器",
            "description": "接通 tax、logistics、email、sms，并为财务、仓储、通知、报表页面提供真实调用链。",
        },
        {
            "id": "A8-103",
            "title": "整合硬件接口与健康面板",
            "description": "把 weighing、bank、attendance 接入统一健康聚合和设置页测试入口。",
        },
    ],
    "A9": [
        {
            "id": "A9-001",
            "title": "66 屏 smoke 与前端回归",
            "description": "按 SCREEN_MANIFEST 覆盖全部页面入口、模板渲染、页面 smoke 与前端截图回归。",
        },
        {
            "id": "A9-002",
            "title": "跨模块链路与权限矩阵回归",
            "description": "覆盖采购-库存-财务、销售-履约-回款、OA-HR 审批链以及角色权限矩阵。",
        },
    ],
}


@dataclass
class LaneSpec:
    lane: str
    name: str
    scope: str
    blocked_by: list[str] = field(default_factory=list)
    handoff_to: list[str] = field(default_factory=list)
    tests: str = ""
    prompt_path: str = ""
    template_path: str = ""
    agent_type: AgentType = AgentType.CODEX


@dataclass
class ScreenSpec:
    screen_id: str
    title: str
    lane: str
    module: str
    status: str
    mockup: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class OssModuleSpec:
    id: str
    name: str
    package: str
    repo: str
    kind: str
    license: str
    stars: int
    lanes: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    why: str = ""
    integration_points: list[str] = field(default_factory=list)


@dataclass
class KeySlotSpec:
    id: str
    lanes: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    ui_anchor: str = ""
    settings_anchor: list[str] = field(default_factory=list)
    notes: str = ""


def is_duerp_project(project_dir: str) -> bool:
    return (Path(project_dir) / DUERP_MASTER_PLAN).exists()


def resolve_main_branch(project_dir: str, fallback: str) -> str:
    return DUERP_MAIN_BRANCH if is_duerp_project(project_dir) else fallback


def resolve_branch_prefix(project_dir: str, fallback: str) -> str:
    return DUERP_BRANCH_PREFIX if is_duerp_project(project_dir) else fallback


def agent_type_for_lane(lane: str) -> AgentType:
    return DUERP_LANE_AGENT_TYPES.get(_duerp_base_lane(lane), AgentType.CODEX)


def _duerp_base_lane(lane: str) -> str:
    return lane.split("-", 1)[0]


def load_lane_specs(project_dir: str) -> dict[str, LaneSpec]:
    return _load_lane_specs_cached(str(Path(project_dir).resolve()))


@lru_cache(maxsize=16)
def _load_lane_specs_cached(project_dir: str) -> dict[str, LaneSpec]:
    root = Path(project_dir)
    prompts_dir = root / DUERP_PROMPTS_DIR
    specs: dict[str, LaneSpec] = {}
    if not prompts_dir.exists():
        return specs

    for path in sorted(prompts_dir.glob("lane-a*.md")):
        text = path.read_text()
        header = re.search(r"#\s+Lane\s+(A\d+)\s+—\s+(.+)", text)
        if not header:
            continue
        lane = header.group(1)
        agent_type = agent_type_for_lane(lane)
        specs[lane] = LaneSpec(
            lane=lane,
            name=header.group(2).strip(),
            scope=_extract_prompt_value(text, "范围"),
            blocked_by=_split_csvish(_extract_prompt_value(text, "blocked_by")),
            handoff_to=_split_csvish(_extract_prompt_value(text, "handoff_to")),
            tests=_extract_prompt_value(text, "tests"),
            prompt_path=str(path),
            template_path=str(prompts_dir / (
                "claude-lane-template.md" if agent_type == AgentType.CLAUDE
                else "codex-lane-template.md"
            )),
            agent_type=agent_type,
        )
    return specs


def load_screen_manifest(project_dir: str) -> list[ScreenSpec]:
    return _load_screen_manifest_cached(str(Path(project_dir).resolve()))


@lru_cache(maxsize=16)
def _load_screen_manifest_cached(project_dir: str) -> list[ScreenSpec]:
    path = Path(project_dir) / DUERP_SCREEN_MANIFEST
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return [ScreenSpec(**item) for item in payload]


def load_oss_modules(project_dir: str) -> list[OssModuleSpec]:
    return _load_oss_modules_cached(str(Path(project_dir).resolve()))


@lru_cache(maxsize=16)
def _load_oss_modules_cached(project_dir: str) -> list[OssModuleSpec]:
    path = Path(project_dir) / DUERP_OSS_MODULES
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return [OssModuleSpec(**item) for item in payload]


def load_key_slots(project_dir: str) -> list[KeySlotSpec]:
    return _load_key_slots_cached(str(Path(project_dir).resolve()))


@lru_cache(maxsize=16)
def _load_key_slots_cached(project_dir: str) -> list[KeySlotSpec]:
    path = Path(project_dir) / DUERP_KEY_SLOTS
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return [KeySlotSpec(**item) for item in payload]


def load_lane_prompt_bundle(project_dir: str, lane: str) -> str:
    specs = load_lane_specs(project_dir)
    spec = specs.get(_duerp_base_lane(lane))
    if spec is None:
        return ""

    template = Path(spec.template_path).read_text() if spec.template_path else ""
    lane_prompt = Path(spec.prompt_path).read_text() if spec.prompt_path else ""
    return (template.strip() + "\n\n" + lane_prompt.strip()).strip()


def build_duerp_modules(project_dir: str) -> list[Module]:
    lane_specs = load_lane_specs(project_dir)
    screens = load_screen_manifest(project_dir)
    screens_by_lane: dict[str, list[ScreenSpec]] = {}
    for screen in screens:
        screens_by_lane.setdefault(screen.lane, []).append(screen)

    modules: list[Module] = []
    module_order = ["A1", "A7-core", "A8-core", "A2", "A3", "A5", "A4", "A6", "A7", "A8", "A9"]

    for module_id in module_order:
        lane = _duerp_base_lane(module_id)
        lane_spec = lane_specs.get(lane)
        if lane_spec is None:
            continue

        owned_paths = list(DUERP_MODULE_OWNED_PATHS.get(module_id, []))
        tasks = []

        for static_task in DUERP_STATIC_TASKS.get(module_id, []):
            tasks.append(Task(
                id=static_task["id"],
                title=static_task["title"],
                description=_compose_task_description(
                    lane_spec, static_task["description"], project_dir, None,
                ),
                module_id=module_id,
                files=owned_paths or ["docs/parallel/"],
                forbidden_files=_forbidden_for_module(module_id),
                dependencies=[],
                agent_type=lane_spec.agent_type,
                owner_lane=module_id,
            ))

        if module_id in {"A2", "A3", "A4", "A5", "A6", "A7"}:
            for screen in screens_by_lane.get(lane, []):
                if screen.status == "implemented":
                    continue
                task_id = f"{module_id}-{screen.screen_id}"
                dependencies = _infer_screen_dependencies(screen, screens_by_lane.get(lane, []), module_id)
                tasks.append(Task(
                    id=task_id,
                    title=screen.title,
                    description=_compose_task_description(
                        lane_spec,
                        f"实现屏幕 {screen.screen_id}：{screen.title}",
                        project_dir,
                        screen,
                    ),
                    module_id=module_id,
                    files=_file_hints_for_screen(screen, module_id) or owned_paths,
                    forbidden_files=_forbidden_for_module(module_id),
                    dependencies=dependencies,
                    agent_type=lane_spec.agent_type,
                    owner_lane=module_id,
                ))

        modules.append(Module(
            id=module_id,
            name=_module_display_name(module_id, lane_spec.name),
            phase=DUERP_LANE_PHASES[module_id],
            owned_paths=owned_paths,
            tasks=tasks,
        ))

    return modules


def resolve_task_scoped_pytest_targets(project_dir: str, tasks: list[Task]) -> list[str]:
    if not is_duerp_project(project_dir):
        return []

    lanes = {
        _duerp_base_lane(task.owner_lane or task.module_id)
        for task in tasks
        if task.id
    }
    targets: list[str] = []
    for lane in sorted(lanes):
        targets.extend(DUERP_LANE_TEST_TARGETS.get(lane, []))

    if any(_task_is_frontend(task) for task in tasks):
        targets.extend(["test/test_view_smoke.py", "test/test_run19_frontend.py"])

    return _dedupe_preserve(targets)


def find_duerp_lane_for_path(filepath: str) -> str:
    normalized = filepath.lstrip("./")
    best_lane = ""
    best_specificity = (-1, -1)
    for lane, patterns in DUERP_MODULE_OWNED_PATHS.items():
        for pattern in patterns:
            if not _owned_path_matches(normalized, pattern):
                continue
            specificity = _owned_path_specificity(pattern)
            if specificity > best_specificity:
                best_lane = lane
                best_specificity = specificity
    return best_lane


def _module_display_name(module_id: str, base_name: str) -> str:
    if module_id == "A7-core":
        return f"{base_name} Core"
    if module_id == "A8-core":
        return f"{base_name} Core"
    return base_name


def _forbidden_for_module(module_id: str) -> list[str]:
    forbidden = list(PROTECTED_FILES)
    owned_paths = DUERP_MODULE_OWNED_PATHS.get(module_id, [])
    for other_module, owned in DUERP_MODULE_OWNED_PATHS.items():
        if other_module == module_id:
            continue
        for path in owned:
            if _path_is_carved_out(path, owned_paths):
                continue
            forbidden.append(path)
    return _dedupe_preserve(forbidden)


def _owned_path_matches(filepath: str, pattern: str) -> bool:
    normalized_pattern = pattern.lstrip("./")
    if filepath == normalized_pattern:
        return True
    if normalized_pattern.endswith("/") and filepath.startswith(normalized_pattern):
        return True
    if any(char in normalized_pattern for char in "*?["):
        return fnmatch.fnmatch(filepath, normalized_pattern)
    return False


def _owned_path_specificity(pattern: str) -> tuple[int, int]:
    normalized = pattern.lstrip("./")
    if any(char in normalized for char in "*?["):
        kind = 1
    elif normalized.endswith("/"):
        kind = 2
    else:
        kind = 3
    return kind, len(normalized.rstrip("/"))


def _path_is_carved_out(candidate: str, owned_paths: list[str]) -> bool:
    """Check if a candidate forbidden path is already covered by an owned path.

    Rules:
    - Exact match → always carve out.
    - Candidate is a directory, owned is a *file* inside it → carve out
      (the scope check prevents touching other files in the directory).
    - Candidate is a directory, owned is a *subdirectory* → do NOT carve out.
      A child directory (e.g. procurement/tests/) must not carve out its
      parent (procurement/) — that would expose non-owned siblings like
      procurement/models.py.
    """
    candidate_norm = candidate.lstrip("./")
    for owned in owned_paths:
        owned_norm = owned.lstrip("./")
        if candidate_norm == owned_norm:
            return True
        if (candidate_norm.endswith("/")
                and not owned_norm.endswith("/")
                and owned_norm.startswith(candidate_norm)):
            return True
    return False


def _owned_paths_overlap(left: str, right: str) -> bool:
    left_norm = left.lstrip("./")
    right_norm = right.lstrip("./")
    if left_norm == right_norm:
        return True
    if left_norm.endswith("/") and right_norm.startswith(left_norm):
        return True
    if right_norm.endswith("/") and left_norm.startswith(right_norm):
        return True
    if any(char in left_norm for char in "*?[") and fnmatch.fnmatch(right_norm.rstrip("/"), left_norm):
        return True
    if any(char in right_norm for char in "*?[") and fnmatch.fnmatch(left_norm.rstrip("/"), right_norm):
        return True
    return False


def _compose_task_description(
    lane_spec: LaneSpec,
    summary: str,
    project_dir: str,
    screen: ScreenSpec | None,
) -> str:
    lines = [
        summary,
        "",
        f"Lane: {lane_spec.lane} — {lane_spec.name}",
        f"Scope: {lane_spec.scope}",
        f"Blocked by: {', '.join(lane_spec.blocked_by) or 'none'}",
        f"Handoff to: {', '.join(lane_spec.handoff_to) or 'none'}",
        f"Tests: {lane_spec.tests}",
        f"Prompt: {lane_spec.prompt_path}",
    ]
    if screen is not None:
        lines.append(f"Screen: {screen.screen_id} [{screen.status}]")
        lines.append(f"Module: {screen.module}")
        if screen.mockup:
            lines.append(
                f"Mockup: docs/成品要求（效果图加文档）/{screen.mockup}"
            )
    context_hints = _build_context_hints(project_dir, lane_spec.lane, screen)
    if context_hints:
        lines.extend(["", context_hints])
    return "\n".join(lines)


def _file_hints_for_screen(screen: ScreenSpec, module_id: str) -> list[str]:
    hints = list(DUERP_MODULE_FILE_HINTS.get(screen.module, []))
    if hints:
        return hints
    return list(DUERP_MODULE_OWNED_PATHS.get(module_id, []))


def _infer_screen_dependencies(
    screen: ScreenSpec, lane_screens: list[ScreenSpec], module_id: str,
) -> list[str]:
    if "详情" not in screen.title and "画像" not in screen.title and "新建" not in screen.title:
        return []

    for candidate in lane_screens:
        if candidate.screen_id == screen.screen_id:
            continue
        if candidate.module != screen.module:
            continue
        if "列表" in candidate.title or "中心" in candidate.title or "台账" in candidate.title:
            return [f"{module_id}-{candidate.screen_id}"]
    return []


def _task_is_frontend(task: Task) -> bool:
    haystacks = [task.title.lower(), task.description.lower()]
    haystacks.extend(filepath.lower() for filepath in task.files)
    markers = ("templates/", "static/", "screen", "page", "layout", "dashboard", "mockup")
    return any(marker in haystack for haystack in haystacks for marker in markers)


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _extract_prompt_value(text: str, label: str) -> str:
    match = re.search(rf"-\s+{re.escape(label)}：(.+)", text)
    return match.group(1).strip() if match else ""


def _split_csvish(value: str) -> list[str]:
    if not value or value == "无":
        return []
    value = value.replace("、", ",")
    return [chunk.strip() for chunk in value.split(",") if chunk.strip()]


def _build_context_hints(project_dir: str, lane: str, screen: ScreenSpec | None) -> str:
    module = screen.module if screen is not None else ""
    targets = {screen.screen_id} if screen is not None else set()

    oss_matches = _select_oss_modules(project_dir, lane, module, targets)
    key_matches = _select_key_slots(project_dir, lane, module, targets)

    lines = []
    if oss_matches:
        lines.append("Approved OSS candidates:")
        for candidate in oss_matches[:4]:
            lines.append(
                f"- {candidate.name} ({candidate.package}) | {candidate.repo} | "
                f"{candidate.license} | stars={candidate.stars} | {candidate.why}"
            )
            if candidate.integration_points:
                lines.append(
                    f"  integration points: {', '.join(candidate.integration_points)}"
                )
    if key_matches:
        lines.append("Key slots / secret placeholders:")
        for slot in key_matches[:4]:
            lines.append(
                f"- {slot.id}: env={', '.join(slot.env_vars)} | ui={slot.ui_anchor} | "
                f"settings={', '.join(slot.settings_anchor)}"
            )
            if slot.notes:
                lines.append(f"  notes: {slot.notes}")
    if lines:
        lines.append("Never commit real secrets; reserve positions only.")
    return "\n".join(lines)


def _select_oss_modules(
    project_dir: str, lane: str, module: str, targets: set[str],
) -> list[OssModuleSpec]:
    matches: list[tuple[int, OssModuleSpec]] = []
    for candidate in load_oss_modules(project_dir):
        score = 0
        if targets.intersection(candidate.targets):
            score += 4
        if module and module in candidate.modules:
            score += 2
        if lane in candidate.lanes:
            score += 1
        if score:
            matches.append((score, candidate))
    matches.sort(key=lambda item: (-item[0], item[1].name))
    return [candidate for _, candidate in matches]


def _select_key_slots(
    project_dir: str, lane: str, module: str, targets: set[str],
) -> list[KeySlotSpec]:
    matches: list[tuple[int, KeySlotSpec]] = []
    for slot in load_key_slots(project_dir):
        score = 0
        if targets.intersection(slot.targets):
            score += 4
        if module and module in slot.modules:
            score += 2
        if lane in slot.lanes:
            score += 1
        if score:
            matches.append((score, slot))
    matches.sort(key=lambda item: (-item[0], item[1].id))
    return [slot for _, slot in matches]
