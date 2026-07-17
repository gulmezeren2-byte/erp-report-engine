"""Fuzz the guard: the corpus proves it catches known attacks; this proves it
does not catch them by memorising their exact spelling.

The corpus is a fixed set of hand-written statements. A guard could pass all of
them and still be defeated by an uppercase function name, a space before a
parenthesis, or a differently-named table. These property tests dress the same
kinds of attack up thousands of ways and assert the guard still refuses every
one - and, in the other direction, that a plain read with arbitrary (safe)
identifiers is still allowed, so "refuse everything" is not how it passes.

The dangerous-function list is imported from the guard itself, so a name added
to the denylist is fuzzed here automatically, without touching this file.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from erp_report_engine.connect import ReadOnlyViolation, assert_read_only
from erp_report_engine.guard import _DANGEROUS_FUNCS

_DIALECTS = ["postgres", "tsql", "mysql", "sqlite"]
_GAP = st.sampled_from(["", " ", "  ", "\t", "\n", " \t "])          # valid inter-token space
_ARG = st.sampled_from(["", "1", "'/etc/passwd'", "42, 1", "'x'"])   # a few harmless argument shapes
# a table/column identifier that cannot collide with a keyword or a denylisted
# function name (both prefixed), so a generated read is unambiguously a read
_IDENT = st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True)


def _mixed_case(word: str, flips) -> str:
    """Recase `word` per a list of booleans - the same name, spelled loudly.

    The flips are cycled so a short list still recases the *whole* word rather
    than truncating it (zip would have shortened the name and changed which
    function it is - which is not the thing under test)."""
    if not flips:
        return word
    return "".join(c.upper() if flips[i % len(flips)] else c.lower()
                   for i, c in enumerate(word))


@settings(deadline=None, max_examples=200)
@given(
    fn=st.sampled_from(sorted(_DANGEROUS_FUNCS)),
    gap=_GAP,
    arg=_ARG,
    dialect=st.sampled_from(_DIALECTS),
    flips=st.lists(st.booleans(), min_size=0, max_size=40),
)
def test_dangerous_function_is_refused_however_it_is_dressed(fn, gap, arg, dialect, flips):
    """A denylisted function inside a well-formed SELECT is refused no matter the
    case, the whitespace before its parenthesis, or its arguments."""
    name = _mixed_case(fn, flips) if flips else fn
    sql = f"SELECT {name}{gap}({arg})"
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(sql, dialect=dialect)


_WRITE_TEMPLATES = [
    "DROP TABLE {id}",
    "DELETE FROM {id}",
    "UPDATE {id} SET x = 1",
    "INSERT INTO {id} VALUES (1)",
    "TRUNCATE TABLE {id}",
    "ALTER TABLE {id} ADD c int",
    "CREATE TABLE {id} (c int)",
]


@settings(deadline=None)
@given(template=st.sampled_from(_WRITE_TEMPLATES), ident=_IDENT, dialect=st.sampled_from(_DIALECTS))
def test_writes_are_refused_for_any_identifier(template, ident, dialect):
    """A write is a write whatever it touches - the object name never rescues it."""
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(template.format(id=ident), dialect=dialect)


@settings(deadline=None)
@given(second=st.sampled_from(["DROP TABLE t", "SELECT 2", "UPDATE t SET x=1", "-- c"]),
       dialect=st.sampled_from(_DIALECTS))
def test_a_second_statement_is_always_refused(second, dialect):
    """Anything smuggled behind a legitimate read as a second statement is refused."""
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(f"SELECT 1; {second}", dialect=dialect)


@settings(deadline=None)
@given(col=_IDENT, tbl=_IDENT, upper=st.booleans(), dialect=st.sampled_from(_DIALECTS))
def test_a_plain_read_with_arbitrary_identifiers_is_allowed(col, tbl, upper, dialect):
    """The other direction: a real read passes with any safe identifiers, in either
    keyword case - the guard is selective, not just a wall. Identifiers are
    prefixed so they cannot collide with a keyword or a denylisted function."""
    kw = ("SELECT", "FROM") if upper else ("select", "from")
    sql = f"{kw[0]} c_{col} {kw[1]} t_{tbl}"
    assert_read_only(sql, dialect=dialect)  # must not raise
