from pathlib import Path

from ownership import find_owner_lane, load_ownership


def test_load_ownership_parses_shared_and_lane_rules(tmp_path) -> None:
    ownership_dir = tmp_path / "docs" / "parallel"
    ownership_dir.mkdir(parents=True)
    (ownership_dir / "OWNERSHIP.md").write_text(
        "# Ownership\n\n"
        "## 共享文件 Owner\n\n"
        "- `A1`：`templates/base.html`、`templates/components/*`\n\n"
        "## Lane 可改范围\n\n"
        "### A4 销售仓储\n\n"
        "- `sales/*`\n"
        "- `warehouse/*`\n\n"
        "禁止：\n\n"
        "- `core/integrations/*`\n"
    )

    ownership = load_ownership(str(tmp_path))

    assert ownership.source_path.endswith("OWNERSHIP.md")
    assert ("templates/base.html", "A1") in ownership.shared_rules
    assert ownership.lane_allowed["A4"] == ["sales/*", "warehouse/*"]
    assert ownership.lane_forbidden["A4"] == ["core/integrations/*"]


def test_find_owner_lane_prefers_shared_rules(tmp_path) -> None:
    ownership_dir = tmp_path / "docs" / "parallel"
    ownership_dir.mkdir(parents=True)
    (ownership_dir / "OWNERSHIP.md").write_text(
        "# Ownership\n\n"
        "## 共享文件 Owner\n\n"
        "- `A8`：`core/integrations/*`\n\n"
        "## Lane 可改范围\n\n"
        "### A4 销售仓储\n\n"
        "- `sales/*`\n"
    )

    ownership = load_ownership(str(tmp_path))

    assert find_owner_lane("core/integrations/adapters/tax.py", ownership) == "A8"
    assert find_owner_lane("sales/views.py", ownership) == "A4"
