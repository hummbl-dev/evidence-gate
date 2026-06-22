#!/usr/bin/env python3
"""Run Evidence-Gate v2 fixtures embedded in PROJECTS/arbiter/rules/*.toml.

This is the Arbiter-side harness for the codex-owned (c)+(d) lane after
hummbl-production PR #225. It intentionally reuses the merged
``hummbl-production/scripts/rule_loader.py`` contract instead of forking a
second parser.

The rule loader is vendored into ``scripts/rule_loader.py`` (see issue #4)
so that CI does not require cross-repo access to the private
hummbl-production repository. If ``HUMMBL_PRODUCTION_ROOT`` is set or a
sibling ``../hummbl-production`` checkout is present, the upstream loader
is used instead to stay aligned with the canonical source.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from pathlib import Path
from typing import Any


ARB_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ARB_ROOT / "rules"
SCRIPTS_DIR = Path(__file__).resolve().parent


def _find_hummbl_production_root(rule_loader_path: Path | None = None) -> Path | None:
    if rule_loader_path is not None:
        path = rule_loader_path.expanduser().resolve()
        if path.is_file() and path.name == "rule_loader.py":
            return path.parent.parent
        if (path / "scripts" / "rule_loader.py").is_file():
            return path
        return None

    env = os.environ.get("HUMMBL_PRODUCTION_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if (root / "scripts" / "rule_loader.py").is_file():
            return root
    sibling = (ARB_ROOT.parent / "hummbl-production").resolve()
    if (sibling / "scripts" / "rule_loader.py").is_file():
        return sibling
    return None


def _load_rule_loader(hummbl_production_root: Path | None) -> Any:
    """Load the rule_loader module.

    Prefers the upstream hummbl-production copy when available (so local
    development stays aligned with the canonical source). Falls back to the
    vendored copy in ``scripts/rule_loader.py`` so that CI works without
    cross-repo access (issue #4).
    """
    if hummbl_production_root is not None:
        sys.path.insert(0, str(hummbl_production_root / "scripts"))
        return importlib.import_module("rule_loader")
    # Vendored fallback — same directory as this harness.
    sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("rule_loader")


VERIFY_WITH_BASIS_RE = re.compile(r"\[VERIFY:\s*[^\]\s][^\]]*\]", re.IGNORECASE)


def _surface_context(surface: str | None) -> set[str]:
    if not surface:
        return set()
    normalized = surface.replace("\\", "/")
    if "/web/" in normalized or "/brand/" in normalized or "/decks/" in normalized:
        return {"external_facing_no_canonical_source"}
    return set()


def _family_contexts(loaded: Any, text: str) -> set[str]:
    contexts: set[str] = set()
    for family_name, family in loaded.families.items():
        for tag, pattern in family.context_tags.items():
            if pattern.search(text):
                contexts.add(f"family.{family_name}.{tag}")
    return contexts


def _regex_match(rule: Any, text: str) -> re.Match[str] | None:
    if rule.pattern.kind == "phrase":
        body = rule.pattern.body or ""
        return re.search(re.escape(body), text)
    if rule.pattern.kind == "regex":
        if rule.pattern.compiled is None:
            raise AssertionError(f"{rule.rule_id}: regex rule has no compiled pattern")
        return rule.pattern.compiled.search(text)
    raise AssertionError(f"{rule.rule_id}: not a regex/phrase rule")


def _compound_match(
    rule: Any,
    text: str,
) -> tuple[re.Match[str], Any] | None:
    for branch in rule.pattern.branches:
        m = branch.regex.search(text)
        if m:
            return m, branch
    return None


def _actual_for_fixture(
    rule_loader: Any,
    loaded: Any,
    rule: Any,
    fixture: Any,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Evidence-Gate v2 fixtures against hummbl-production rule_loader.py.",
    )
    parser.add_argument(
        "--rule-loader-path",
        type=Path,
        help=(
            "Path to hummbl-production root or scripts/rule_loader.py. "
            "Defaults to HUMMBL_PRODUCTION_ROOT or sibling ../hummbl-production."
        ),
    )
    parser.add_argument(
        "--skip-missing-loader",
        action="store_true",
        help="Exit 0 instead of failing when hummbl-production rule_loader.py is unavailable.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hummbl_production_root = _find_hummbl_production_root(args.rule_loader_path)
    loader_source: str
    if hummbl_production_root is not None:
        loader_source = str(hummbl_production_root / "scripts" / "rule_loader.py")
    else:
        # Fall back to the vendored copy (issue #4) — no cross-repo access needed.
        vendored = SCRIPTS_DIR / "rule_loader.py"
        if not vendored.is_file():
            message = (
                "SKIP: cannot find rule_loader.py (neither upstream "
                "hummbl-production nor vendored scripts/rule_loader.py); "
                "set HUMMBL_PRODUCTION_ROOT or pass --rule-loader-path"
            )
            if args.skip_missing_loader:
                print(message)
                return 0
            print(f"ERROR: {message.removeprefix('SKIP: ')}", file=sys.stderr)
            return 2
        loader_source = str(vendored)

    rule_loader = _load_rule_loader(hummbl_production_root)
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
            actual = _actual_for_fixture(rule_loader, loaded, rule, fixture)
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
    print(f"loader={loader_source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
