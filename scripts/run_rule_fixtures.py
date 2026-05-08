#!/usr/bin/env python3
"""Run Evidence-Gate v2 fixtures embedded in PROJECTS/arbiter/rules/*.toml.

This is the Arbiter-side harness for the codex-owned (c)+(d) lane after
hummbl-production PR #225. It intentionally reuses the merged
``hummbl-production/scripts/rule_loader.py`` contract instead of forking a
second parser.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any


ARB_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ARB_ROOT / "rules"


def _find_hummbl_production_root() -> Path:
    env = os.environ.get("HUMMBL_PRODUCTION_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if (root / "scripts" / "rule_loader.py").is_file():
            return root
    sibling = (ARB_ROOT.parent / "hummbl-production").resolve()
    if (sibling / "scripts" / "rule_loader.py").is_file():
        return sibling
    raise SystemExit(
        "ERROR: cannot find hummbl-production/scripts/rule_loader.py; "
        "set HUMMBL_PRODUCTION_ROOT"
    )


HUMMBL_PRODUCTION_ROOT = _find_hummbl_production_root()
sys.path.insert(0, str(HUMMBL_PRODUCTION_ROOT / "scripts"))

import rule_loader  # type: ignore  # noqa: E402


VERIFY_WITH_BASIS_RE = re.compile(r"\[VERIFY:\s*[^\]\s][^\]]*\]", re.IGNORECASE)


def _surface_context(surface: str | None) -> set[str]:
    if not surface:
        return set()
    normalized = surface.replace("\\", "/")
    if "/web/" in normalized or "/brand/" in normalized or "/decks/" in normalized:
        return {"external_facing_no_canonical_source"}
    return set()


def _family_contexts(loaded: rule_loader.LoadedRules, text: str) -> set[str]:
    contexts: set[str] = set()
    for family_name, family in loaded.families.items():
        for tag, pattern in family.context_tags.items():
            if pattern.search(text):
                contexts.add(f"family.{family_name}.{tag}")
    return contexts


def _regex_match(rule: rule_loader.Rule, text: str) -> re.Match[str] | None:
    if rule.pattern.kind == "phrase":
        body = rule.pattern.body or ""
        return re.search(re.escape(body), text)
    if rule.pattern.kind == "regex":
        if rule.pattern.compiled is None:
            raise AssertionError(f"{rule.rule_id}: regex rule has no compiled pattern")
        return rule.pattern.compiled.search(text)
    raise AssertionError(f"{rule.rule_id}: not a regex/phrase rule")


def _compound_match(
    rule: rule_loader.Rule,
    text: str,
) -> tuple[re.Match[str], rule_loader.CompoundBranch] | None:
    for branch in rule.pattern.branches:
        m = branch.regex.search(text)
        if m:
            return m, branch
    return None


def _actual_for_fixture(
    loaded: rule_loader.LoadedRules,
    rule: rule_loader.Rule,
    fixture: rule_loader.Fixture,
) -> dict[str, Any]:
    text = fixture.text
    contexts = _surface_context(fixture.surface)
    contexts.update(_family_contexts(loaded, text))
    if VERIFY_WITH_BASIS_RE.search(text):
        contexts.add("marker_present_with_basis")

    if rule.pattern.kind == "compound":
        compound = _compound_match(rule, text)
        if compound is None:
            return {"severity": "NONE"}
        match, branch = compound
        classified = rule_loader.classify_compound(rule, match, branch)
        if "severity" not in classified:
            classified["severity"] = rule_loader.compute_severity(rule, contexts)
        return {
            "severity": classified["severity"],
            "finding": rule.rule_id,
            **{k: v for k, v in classified.items() if k != "branch_id"},
        }

    match = _regex_match(rule, text)
    if match is None:
        return {"severity": "NONE"}

    severity = rule_loader.compute_severity(rule, contexts)
    return {
        "severity": severity,
        "finding": rule.rule_id,
        "context_tags": sorted(c for c in contexts if c.startswith("family.")),
    }


def _matches_expected(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    for key, expected_value in expected.items():
        if key == "reason":
            continue
        actual_value = actual.get(key)
        if actual_value != expected_value:
            return False, f"{key}: expected {expected_value!r}, got {actual_value!r}"
    return True, ""


def main() -> int:
    loaded = rule_loader.load_library(RULES_DIR)
    failures: list[str] = []
    total = 0

    for rule in loaded.rules:
        fixtures = [
            ("positive", fixture) for fixture in rule.fixtures_positive
        ] + [
            ("negative", fixture) for fixture in rule.fixtures_negative
        ]
        for kind, fixture in fixtures:
            total += 1
            actual = _actual_for_fixture(loaded, rule, fixture)
            ok, reason = _matches_expected(actual, fixture.expects)
            if not ok:
                failures.append(
                    f"{rule.rule_id} {kind} fixture {fixture.text!r}: {reason}; "
                    f"actual={actual!r} expected={fixture.expects!r}"
                )

    if failures:
        print(f"FAIL: {len(failures)} of {total} fixtures failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"PASS: {total} fixtures across {len(loaded.rules)} rules")
    print(f"rules_dir={RULES_DIR}")
    print(f"loader={HUMMBL_PRODUCTION_ROOT / 'scripts' / 'rule_loader.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

