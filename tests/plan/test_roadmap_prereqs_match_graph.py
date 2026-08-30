"""
INC-03 — roadmap drift check: for every increment, the Prerequisites line in
increments/*.md, the canonical dependency table in REBUILD_ROADMAP.md, and the
Mermaid graph edges must define IDENTICAL prerequisite sets (24 increments).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPL = ROOT / "docs" / "implementation"

INC_RE = re.compile(r"INC-?(\d{2})")


def _norm(token):
    m = INC_RE.fullmatch(token.strip()) or INC_RE.match(token.strip())
    assert m, f"not an increment token: {token!r}"
    return f"INC-{m.group(1)}"


def _prereqs_from_increment_files():
    result = {}
    current = None
    for md in sorted((IMPL / "increments").glob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            header = re.match(r"^## (INC-\d{2})\b", line)
            if header:
                current = header.group(1)
                continue
            if line.startswith("- **Prerequisites:**") and current:
                field = line.split("**Prerequisites:**", 1)[1]
                tokens = INC_RE.findall(field)
                result[current] = {f"INC-{t}" for t in tokens}
                current_field = field.replace(".", "").strip().lower()
                if not tokens:
                    assert current_field in ("none", "—", "-"), (
                        f"{current}: Prerequisites line is not token-only: {field!r}"
                    )
                current = None
    return result


def _prereqs_from_roadmap_table():
    result = {}
    text = (IMPL / "REBUILD_ROADMAP.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r"^\|\s*(INC-\d{2})\s*\|([^|]*)\|\s*$", line)
        if m:  # two-column rows form the canonical dependency table
            inc, deps = m.group(1), m.group(2)
            result[inc] = {f"INC-{t}" for t in INC_RE.findall(deps)}
    return result


def _prereqs_from_mermaid():
    text = (IMPL / "REBUILD_ROADMAP.md").read_text(encoding="utf-8")
    edges = re.findall(
        r"(INC\d{2})(?:\[[^\]]*\])?\s*-->\s*(INC\d{2})(?:\[[^\]]*\])?", text
    )
    result = {}
    nodes = set()
    for src, dst in edges:
        nodes.update((_norm(src), _norm(dst)))
        result.setdefault(_norm(dst), set()).add(_norm(src))
    for node in nodes:
        result.setdefault(node, set())
    return result


def test_roadmap_prereqs_match_graph():
    from_files = _prereqs_from_increment_files()
    from_table = _prereqs_from_roadmap_table()
    from_graph = _prereqs_from_mermaid()

    expected = {f"INC-{i:02d}" for i in range(24)}
    assert set(from_files) == expected, f"increment files: {sorted(set(from_files) ^ expected)}"
    assert set(from_table) == expected, f"roadmap table: {sorted(set(from_table) ^ expected)}"
    assert set(from_graph) == expected, f"mermaid graph: {sorted(set(from_graph) ^ expected)}"

    for inc in sorted(expected):
        assert from_files[inc] == from_table[inc] == from_graph[inc], (
            f"{inc} drifted: files={sorted(from_files[inc])} "
            f"table={sorted(from_table[inc])} graph={sorted(from_graph[inc])}"
        )
