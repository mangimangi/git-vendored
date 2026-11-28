# check's ** pattern matching over-matches patterns with two **

> Captured: 2026-11-28

## Context

Closing `templates/check` coverage to 99% (gv-f492.2, epic gv-f492). The only line left uncovered is `templates/check:165`, the `return True` of the basename fallback in `matches_any_pattern`. That fallback is reached only when `fnmatch` on the whole pattern has already failed, so it returns True only for a path the pattern does not actually describe. Writing a test for it would lock that wrong behaviour in, so the line was left uncovered. Every `**` pattern in use today is a trailing `dir/**`, which never reaches this branch.

## Idea

templates/check matches_any_pattern over-matches patterns with two ** (e.g. 'a/**/b/**/x.py' matches a/d/x.py) via the basename fallback at templates/check:162-165; line 165 is only reachable through that over-match. Consider replacing the hand-rolled ** handling with a proper glob-to-regex (unit 5 changes check).
