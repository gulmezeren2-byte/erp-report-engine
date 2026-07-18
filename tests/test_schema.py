"""The canonical model contract: what `describe_model`, the `schema` CLI, and the
published docs/model.json all serialise from one source. These pin the contract's
shape and that the published copy cannot drift from the code."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from types import SimpleNamespace

from erp_report_engine.semantic import CANONICAL_SCHEMA, canonical_model

_DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")


def test_canonical_model_covers_every_entity_and_column():
    m = canonical_model()
    assert m["model_version"] and m["notes"]
    assert set(m["entities"]) == set(CANONICAL_SCHEMA)
    for name, spec in CANONICAL_SCHEMA.items():
        ent = m["entities"][name]
        assert ent["required"] == spec["required"]
        assert ent["grain"] == spec["grain"]
        # every column carries a name, type and description, in schema order
        got = [(c["name"], c["type"], c["description"]) for c in ent["columns"]]
        want = [(n, t, d) for n, (t, d) in spec["columns"].items()]
        assert got == want
        assert isinstance(ent["examples"], list)


def test_canonical_model_is_json_serialisable():
    # must round-trip cleanly - it is published as a static file and emitted by the CLI
    assert json.loads(json.dumps(canonical_model()))


def test_schema_cli_emits_the_model():
    from erp_report_engine.cli import cmd_schema

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_schema(SimpleNamespace())
    assert json.loads(buf.getvalue()) == canonical_model()


def test_published_model_json_matches_the_code():
    """docs/model.json is regenerated in CI and drift-gated; assert it in-process
    too, so a stale published contract fails the tests, not just the CI gate."""
    path = os.path.join(_DOCS, "model.json")
    with open(path, encoding="utf-8") as f:
        published = json.load(f)
    assert published == canonical_model(), "docs/model.json is stale — run docs/generate_model_json.py"
