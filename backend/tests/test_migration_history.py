from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations" / "versions"
MANIFEST = BACKEND / "migrations" / "released-migrations.sha256.json"


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} is missing {name}")


def test_released_migrations_are_immutable_and_form_one_chain():
    files = sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(manifest) == {path.name for path in files}

    revisions: dict[str, str | None] = {}
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == manifest[path.name], f"已发布迁移禁止删除或改写：{path.name}"
        revision = _literal_assignment(path, "revision")
        down_revision = _literal_assignment(path, "down_revision")
        assert path.name.startswith(f"{revision}_")
        revisions[revision] = down_revision

    ordered = sorted(revisions)
    assert ordered == [f"{number:04d}" for number in range(1, len(ordered) + 1)]
    assert revisions[ordered[0]] is None
    for previous, current in zip(ordered[:-1], ordered[1:], strict=True):
        assert revisions[current] == previous
    assert set(ordered) - {value for value in revisions.values() if value} == {ordered[-1]}
