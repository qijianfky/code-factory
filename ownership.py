"""Read ownership rules from project docs."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


OWNERSHIP_PATHS = (
    "docs/parallel/OWNERSHIP.md",
)


@dataclass
class OwnershipConfig:
    source_path: str = ""
    shared_rules: list[tuple[str, str]] = field(default_factory=list)
    lane_allowed: dict[str, list[str]] = field(default_factory=dict)
    lane_forbidden: dict[str, list[str]] = field(default_factory=dict)


def load_ownership(project_dir: str) -> OwnershipConfig:
    """Load ownership rules from the target project if available."""
    return _load_ownership_cached(str(Path(project_dir).resolve()))


@lru_cache(maxsize=16)
def _load_ownership_cached(project_dir: str) -> OwnershipConfig:
    root = Path(project_dir)
    ownership_file = next(
        (root / candidate for candidate in OWNERSHIP_PATHS if (root / candidate).exists()),
        None,
    )
    if ownership_file is None:
        return OwnershipConfig()

    return _parse_ownership(ownership_file)


def find_owner_lane(filepath: str, ownership: OwnershipConfig) -> str:
    """Resolve the lane that owns a given path."""
    for pattern, lane in ownership.shared_rules:
        if _matches(filepath, pattern):
            return lane

    matches = []
    for lane, patterns in ownership.lane_allowed.items():
        if any(_matches(filepath, pattern) for pattern in patterns):
            matches.append(lane)

    if len(matches) == 1:
        return matches[0]
    return ""


def _parse_ownership(path: Path) -> OwnershipConfig:
    config = OwnershipConfig(source_path=str(path))
    section = ""
    current_lane = ""
    parse_forbidden = False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            current_lane = ""
            parse_forbidden = False
            continue
        if line.startswith("### "):
            lane_match = re.match(r"###\s+(A\d+)\b", line)
            current_lane = lane_match.group(1) if lane_match else ""
            parse_forbidden = False
            continue
        if line == "禁止：":
            parse_forbidden = True
            continue
        if not line.startswith("- "):
            continue

        values = re.findall(r"`([^`]+)`", line)
        if not values:
            continue

        if section == "共享文件 Owner":
            lane, *patterns = values
            config.shared_rules.extend((pattern, lane) for pattern in patterns)
            continue

        if current_lane:
            target = config.lane_forbidden if parse_forbidden else config.lane_allowed
            target.setdefault(current_lane, []).extend(values)

    return config


def _matches(filepath: str, pattern: str) -> bool:
    normalized = filepath.lstrip("./")
    normalized_pattern = pattern.lstrip("./")

    if normalized == normalized_pattern:
        return True
    if normalized_pattern.endswith("/") and normalized.startswith(normalized_pattern):
        return True
    return fnmatch.fnmatch(normalized, normalized_pattern)
