"""Check local Markdown targets and the stable numbered TODO catalogue."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"NOT_STARTED", "IN_PROGRESS", "BLOCKED", "DONE"}


def check(root: Path = ROOT) -> dict[str, int]:
    documents = list(root.glob("*.md")) + [
        path for path in (root / "docs").rglob("*.md") if "node_modules" not in path.parts
    ]
    targets = 0
    for path in documents:
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for destination in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            if destination.startswith(("https://", "http://", "#", "mailto:")):
                continue
            target = unquote(destination.split("#")[0])
            if not target:
                continue
            assert (path.parent / target).exists(), f"Missing link in {path.name}: {target}"
            targets += 1
    files = sorted((root / "TODO").glob("*.todo"))
    index = (root / "TODO" / "00_INDEX.todo").read_text(encoding="utf-8")
    rows = dict(re.findall(r"(\d{2}_[A-Z0-9_]+\.todo)\s+([A-Z_]+)", index))
    dependencies: dict[str, list[str]] = {}
    states = {}
    required_sections = (
        "Purpose",
        "Tasks",
        "Acceptance criteria",
        "Completion evidence",
        "Completion log",
    )
    for path in files:
        if path.name == "00_INDEX.todo":
            continue
        text = path.read_text(encoding="utf-8")
        assert re.fullmatch(r"\d{2}_[A-Z0-9_]+\.todo", path.name)
        status = re.search(r"^Status: (.+)$", text, re.M).group(1)
        assert status in STATUSES, f"Invalid status: {path.name}"
        assert rows.get(path.name) == status, f"Index differs from {path.name}"
        assert all(f"## {section}" in text for section in required_sections), path.name
        deps = re.search(r"^Dependencies: (.+)$", text, re.M).group(1)
        dependencies[path.name] = [] if deps == "None" else [d.strip() for d in deps.split(",")]
        states[path.name] = status
        if status == "DONE":
            assert "- [ ]" not in text, f"Unchecked DONE work: {path.name}"
            assert "None yet" not in text, f"Missing completion evidence: {path.name}"
    visited, visiting = set(), set()

    def walk(name):
        assert name not in visiting, f"Cyclic TODO dependency: {name}"
        if name in visited:
            return
        visiting.add(name)
        for dep in dependencies[name]:
            assert dep in dependencies, f"Missing TODO dependency: {name} -> {dep}"
            if states[name] == "DONE":
                assert states[dep] == "DONE", f"Unmet DONE dependency: {name} -> {dep}"
            walk(dep)
        visiting.remove(name)
        visited.add(name)

    for name in dependencies:
        walk(name)
    assert set(rows) == set(states), "TODO index has missing or extra workstreams."
    return {"markdown_files": len(documents), "local_links": targets, "workstreams": len(states)}


if __name__ == "__main__":
    print(check())
