"""Naive read-only checks - the ones real tools actually ship - as baselines.

The trust benchmark's point is not "our guard passes our tests"; any guard
passes its own tests. The point is the *contrast*: the same corpus that this
project's guard clears is waved-through by the shape-only checks that are
common in the wild. To make that contrast a measured fact rather than an
assertion, this module implements those naive checks and runs the exact same
corpus through them (see `attack_corpus.compare`).

These are deliberately faithful, not strawmen. Each is something a competent
engineer has shipped as "read-only enforcement":

* `starts_with_select` - "if it starts with SELECT/WITH it's a read." This is
  the single most common text-to-SQL guardrail; it is exactly what lets a
  `SELECT pg_read_file(...)`, a `SELECT ... INTO OUTFILE`, an
  `INSERT`-inside-a-CTE, or a `SELECT 1; DROP TABLE t` straight through - all
  well-formed, all leading with the right keyword.

* `write_keyword_blocklist` - "reject if the text contains a write keyword."
  The other common pattern. It is both unsafe (a file-reading or socket-opening
  function contains none of the blocked words) *and* unusable (the word
  `delete` inside a string literal trips it), so it manages to miss real
  attacks while blocking a legitimate read - the worst of both.

Each function takes the same `(sql, dialect=None)` shape as the engine's own
`assert_read_only`, and raises `ReadOnlyViolation` to signal a block, so the
corpus runner can point at any of them interchangeably. They depend on nothing
heavier than `re`, on purpose - a naive guard is naive precisely because it
never parses the statement.
"""

from __future__ import annotations

import re

from .errors import ReadOnlyViolation

# The lenient shape check: a statement is treated as a read if its first
# keyword is SELECT or WITH. Deliberately linear (a leading `\s*` over a fixed
# alternation, then a word boundary) - a naive guard is naive precisely because
# it does no real parsing, and it certainly should not open itself to
# regex-denial-of-service while pretending to.
_HEAD = re.compile(r"\s*(?:select|with)\b", re.IGNORECASE)


def starts_with_select(sql: str, dialect: str | None = None) -> None:
    """Allow anything whose first keyword is SELECT or WITH; block the rest.

    The most common text-to-SQL read-only check. It cannot see past the first
    token, so every SELECT-shaped side effect and every read with a second
    statement smuggled behind it sails through.
    """
    if not _HEAD.match(sql or ""):
        raise ReadOnlyViolation("does not begin with SELECT/WITH")


# A representative write-keyword blocklist, matched case-insensitively as a
# substring - the naive way, which is what makes it both leaky and brittle.
_BLOCKLIST = (
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "replace", "grant", "revoke", "exec", "merge", "call",
)


def write_keyword_blocklist(sql: str, dialect: str | None = None) -> None:
    """Block if the statement text contains any blocklisted write keyword.

    Substring, case-insensitive - so `default_transaction_read_only` is fine but
    a note reading `'please delete this note'` is not, and a function that reads
    a file or opens a socket (none of these words in sight) is waved through.
    """
    low = (sql or "").lower()
    hit = next((kw for kw in _BLOCKLIST if kw in low), None)
    if hit is not None:
        raise ReadOnlyViolation(f"contains the blocklisted keyword {hit!r}")


def baselines() -> dict:
    """The labeled set of naive guards, so the CLI and the results page compare
    against the same baselines (one definition, every surface)."""
    return {
        "starts-with-SELECT": starts_with_select,
        "write-keyword blocklist": write_keyword_blocklist,
    }
