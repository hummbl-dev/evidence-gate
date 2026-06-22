#!/usr/bin/env python3
"""
HUMMBL Evidence-Gate v2 rule loader.

VENDORED COPY — sourced from hummbl-production/scripts/rule_loader.py.
This file is vendored into evidence-gate so that the fixture CI workflow
does not require cross-repository access to the private hummbl-production
repository (see issue #4). Keep this copy in sync with the canonical
upstream in hummbl-production/scripts/rule_loader.py.

Reads declarative rule definitions from a TOML rule library
(typically ``PROJECTS/arbiter/rules/``) and turns them into compiled,
validated objects that ``case_study_verify`` and other consumers can
drive their findings off of.

Design contract (Stage-2 schema v0.2, codex ACK 2026-05-08T17:55:01Z):

* Stdlib only — ``tomllib`` (Python 3.11+) for TOML, ``re``/``subprocess``/
  ``pathlib`` for everything else. No third-party imports.
* No silent fallback on a malformed library. If a rule library is
  *discovered* but fails validation, raise ``RuleLibraryError`` and let
  the caller exit non-zero. Falling through to the v1 hard-coded
  constants is only legal when no library is discovered at all.
* Path resolution is portable. Roots are resolved in the order declared
  in ``_surfaces.toml`` (env var > relative_to_self > nearest-ancestor
  discovery). No host hardcodes.
* Compound patterns evaluate longest/most-specific branch first. Each
  branch emits an ``emit_context`` so the classifier can dispatch
  post-match (e.g., ER-008 canonical/reordered/missing/misnamed).
* Marker semantics: ``[VERIFY: <basis>]`` demotes by one tier when
  ``by_one_tier`` is set; empty ``[VERIFY:]`` is ignored.

Schema details: see ``_internal/schemas/evidence-gate-v2-schema-2026-05-08.md``
for the authoritative reference. Final schema receipt is targeted at
``PROJECTS/arbiter/docs/evidence-gate-v2-schema.md`` once codex ships
(c)+(d).
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SEVERITY_ORDER = ("INFO", "WARN", "ERROR")
SEVERITY_LEVEL = {name: idx for idx, name in enumerate(SEVERITY_ORDER)}

VERIFY_MARKER_RE = re.compile(r"\[VERIFY:\s*([^\]]*?)\s*\]", re.IGNORECASE)


class RuleLibraryError(Exception):
    """Raised when a rule library is discovered but malformed.

    Callers should treat this as a hard load error (exit 2). It is NOT a
    signal to fall through to v1 hard-coded constants — that fallback is
    only legal when no library is discovered.
    """


# --- Dataclasses ----------------------------------------------------------


@dataclass
class SeverityClause:
    context: str
    to: str | None = None
    by_one_tier: bool = False


@dataclass
class Severity:
    default: str
    promote_when: list[SeverityClause] = field(default_factory=list)
    demote_when: list[SeverityClause] = field(default_factory=list)


@dataclass
class CanonicalSources:
    required: bool
    policy: str
    scope: str | None = None


@dataclass
class Exception_:
    kind: str                       # marker_match | allowlist_match | surface_exempt
    mode: str | None = None         # same_line for marker_match
    basis_required: bool = False


@dataclass
class CompoundBranch:
    branch_id: str
    regex: re.Pattern[str]
    emit_context: str
    capture: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Pattern:
    kind: str                       # regex | phrase | compound
    body: str | None = None
    flags: list[str] = field(default_factory=list)
    capture: list[dict[str, Any]] = field(default_factory=list)
    compiled: re.Pattern[str] | None = None
    branches: list[CompoundBranch] = field(default_factory=list)


@dataclass
class Fixture:
    text: str
    expects: dict[str, Any]
    surface: str | None = None


@dataclass
class Rule:
    rule_id: str
    description: str
    pattern: Pattern
    severity: Severity
    canonical_sources: CanonicalSources
    exceptions: list[Exception_] = field(default_factory=list)
    fixtures_positive: list[Fixture] = field(default_factory=list)
    fixtures_negative: list[Fixture] = field(default_factory=list)


@dataclass
class Family:
    name: str
    context_tags: dict[str, re.Pattern[str]] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class SurfaceRegistry:
    roots: list[dict[str, Any]]
    surfaces: dict[str, list[str]]
    resolved_root: Path | None = None


@dataclass
class LoadedRules:
    rules: list[Rule]
    families: dict[str, Family]
    surfaces: SurfaceRegistry
    library_path: Path

    def by_id(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        raise KeyError(rule_id)


# --- Helpers --------------------------------------------------------------


def _flag_value(name: str) -> int:
    table = {
        "IGNORECASE": re.IGNORECASE,
        "MULTILINE": re.MULTILINE,
        "DOTALL": re.DOTALL,
        "VERBOSE": re.VERBOSE,
        "UNICODE": re.UNICODE,
    }
    if name not in table:
        raise RuleLibraryError(f"unknown regex flag: {name!r}")
    return table[name]


def _compile_regex(body: str, flags: list[str], where: str) -> re.Pattern[str]:
    f = 0
    for fl in flags:
        f |= _flag_value(fl)
    try:
        return re.compile(body, f)
    except re.error as exc:
        raise RuleLibraryError(f"{where}: invalid regex {body!r}: {exc}") from exc


def _require(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RuleLibraryError(f"{where}: missing required field {key!r}")
    return d[key]


def _validate_severity_name(name: str, where: str) -> str:
    if name not in SEVERITY_LEVEL:
        raise RuleLibraryError(f"{where}: severity must be one of {SEVERITY_ORDER}, got {name!r}")
    return name


def demote_one_tier(severity: str) -> str:
    """ERROR -> WARN -> INFO. INFO floors at INFO."""
    idx = SEVERITY_LEVEL[severity]
    return SEVERITY_ORDER[max(0, idx - 1)]


def promote_to(current: str, target: str) -> str:
    """Return whichever of current/target is more severe."""
    return current if SEVERITY_LEVEL[current] >= SEVERITY_LEVEL[target] else target


# --- Severity computer ----------------------------------------------------


def compute_severity(
    rule: Rule,
    contexts: set[str],
) -> str:
    """Apply default + promote_when + demote_when.

    ``contexts`` is the set of context strings (e.g., ``"external_facing_no_canonical_source"``,
    ``"marker_present_with_basis"``) that the verifier has determined apply to a
    given finding. Promotes are applied first, then demotes.
    """
    sev = rule.severity.default
    for clause in rule.severity.promote_when:
        if clause.context in contexts:
            if clause.to is None:
                raise RuleLibraryError(f"{rule.rule_id}: promote_when needs `to`")
            sev = promote_to(sev, _validate_severity_name(clause.to, rule.rule_id))
    for clause in rule.severity.demote_when:
        if clause.context in contexts:
            if clause.by_one_tier:
                sev = demote_one_tier(sev)
            elif clause.to is not None:
                # explicit `to` — only demote if it's actually less severe
                target = _validate_severity_name(clause.to, rule.rule_id)
                if SEVERITY_LEVEL[target] < SEVERITY_LEVEL[sev]:
                    sev = target
            else:
                raise RuleLibraryError(
                    f"{rule.rule_id}: demote_when needs `to` or `by_one_tier=true`"
                )
    return sev


# --- Compound classifier (ER-008 style) -----------------------------------


CANONICAL_BROCCOLILLY = ("S", "T", "I", "C", "D")
CANONICAL_BROCCOLILLY_SET = set(CANONICAL_BROCCOLILLY)
NAMED_BROCCOLILLY = {
    "SENSORY": "S",
    "TEMPORAL": "T",
    "INTERPERSONAL": "I",
    "COGNITIVE": "C",
    "DOMAIN": "D",
}


def _normalize_factor(token: str) -> str:
    """Map raw factor token to its canonical letter, or '' if unrecognized."""
    up = token.upper()
    if up in CANONICAL_BROCCOLILLY_SET:
        return up
    return NAMED_BROCCOLILLY.get(up, "")


def classify_broccolilly(factors: list[str]) -> dict[str, Any]:
    """Classify a list of factor tokens captured by a compound branch.

    Returns a dict like:
        {"classify": "canonical", "form": "letter"}
        {"classify": "missing", "missing_factor": "I", "form": "named"}
        {"classify": "misnamed", "misnamed_factors": ["X"], "form": "letter"}
    """
    normalized = [_normalize_factor(t) for t in factors]
    misnamed = [factors[i] for i, n in enumerate(normalized) if n == ""]
    form = "named" if any(_normalize_factor(t) and t.upper() not in CANONICAL_BROCCOLILLY_SET for t in factors) else "letter"

    if misnamed:
        return {"classify": "misnamed", "misnamed_factors": misnamed, "form": form}

    seen = set(normalized)
    if len(factors) == 5:
        if normalized == list(CANONICAL_BROCCOLILLY):
            return {"classify": "canonical", "form": form}
        if seen == CANONICAL_BROCCOLILLY_SET:
            return {"classify": "reordered", "form": form}
        return {"classify": "misnamed", "misnamed_factors": [], "form": form}
    if len(factors) == 4:
        if seen.issubset(CANONICAL_BROCCOLILLY_SET):
            missing = (CANONICAL_BROCCOLILLY_SET - seen).pop()
            return {"classify": "missing", "missing_factor": missing, "form": form}
        return {"classify": "misnamed", "misnamed_factors": [], "form": form}
    return {"classify": "misnamed", "misnamed_factors": [], "form": form}


def classify_compound(rule: Rule, match: re.Match[str], branch: CompoundBranch) -> dict[str, Any]:
    """Dispatch a compound match to its classifier. Currently ER-008 only.

    Returns a dict augmenting the finding with classification keys
    (e.g., ``classify``, ``missing_factor``) and a derived severity.
    """
    if rule.rule_id == "ER-008-broccolilly-tuple":
        # Captures are positional; build factor list from non-None groups.
        factors = [g for g in match.groups() if g is not None]
        result = classify_broccolilly(factors)
        sev_map = {
            "canonical": "INFO",
            "reordered": "WARN",
            "missing": "ERROR",
            "misnamed": "WARN",
        }
        result["severity"] = sev_map[result["classify"]]
        result["branch_id"] = branch.branch_id
        return result
    # Unknown compound rule: caller should fall back to default severity.
    return {"branch_id": branch.branch_id}


# --- TOML loaders ---------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise RuleLibraryError(f"{path}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise RuleLibraryError(f"{path}: cannot read: {exc}") from exc


def _parse_severity(d: dict[str, Any], where: str) -> Severity:
    default = _validate_severity_name(_require(d, "default", f"{where}.severity"), where)
    promote = []
    for clause in d.get("promote_when", []):
        promote.append(SeverityClause(
            context=_require(clause, "context", f"{where}.severity.promote_when"),
            to=clause.get("to"),
            by_one_tier=bool(clause.get("by_one_tier", False)),
        ))
    demote = []
    for clause in d.get("demote_when", []):
        demote.append(SeverityClause(
            context=_require(clause, "context", f"{where}.severity.demote_when"),
            to=clause.get("to"),
            by_one_tier=bool(clause.get("by_one_tier", False)),
        ))
    return Severity(default=default, promote_when=promote, demote_when=demote)


def _parse_pattern(d: dict[str, Any], where: str) -> Pattern:
    kind = _require(d, "kind", f"{where}.pattern")
    if kind not in ("regex", "phrase", "compound"):
        raise RuleLibraryError(f"{where}.pattern.kind must be regex|phrase|compound, got {kind!r}")
    flags = list(d.get("flags", []))

    if kind == "compound":
        any_of = d.get("any_of", [])
        if not any_of:
            raise RuleLibraryError(f"{where}.pattern: compound kind requires non-empty any_of")
        branches: list[CompoundBranch] = []
        for i, br in enumerate(any_of):
            br_where = f"{where}.pattern.any_of[{i}]"
            branches.append(CompoundBranch(
                branch_id=_require(br, "branch_id", br_where),
                regex=_compile_regex(_require(br, "regex", br_where), list(br.get("flags", flags)), br_where),
                emit_context=_require(br, "emit_context", br_where),
                capture=list(br.get("capture", [])),
            ))
        return Pattern(kind=kind, flags=flags, branches=branches)

    body = _require(d, "body", f"{where}.pattern")
    compiled = _compile_regex(body, flags, f"{where}.pattern")
    return Pattern(kind=kind, body=body, flags=flags, capture=list(d.get("capture", [])), compiled=compiled)


def _parse_canonical_sources(d: dict[str, Any], where: str) -> CanonicalSources:
    valid_policies = {
        "must_match_with_unit",
        "must_match_anywhere",
        "must_match_full_context",
        "git_rev_parse",
        "none",
    }
    policy = _require(d, "policy", f"{where}.canonical_sources")
    if policy not in valid_policies:
        raise RuleLibraryError(
            f"{where}.canonical_sources.policy must be one of {sorted(valid_policies)}, got {policy!r}"
        )
    return CanonicalSources(
        required=bool(_require(d, "required", f"{where}.canonical_sources")),
        policy=policy,
        scope=d.get("scope"),
    )


def _parse_exceptions(items: list[dict[str, Any]], where: str) -> list[Exception_]:
    out = []
    for i, ex in enumerate(items):
        ex_where = f"{where}.exceptions[{i}]"
        out.append(Exception_(
            kind=_require(ex, "kind", ex_where),
            mode=ex.get("mode"),
            basis_required=bool(ex.get("basis_required", False)),
        ))
    return out


def _parse_fixtures(items: list[dict[str, Any]], where: str) -> list[Fixture]:
    out = []
    for i, fx in enumerate(items):
        fx_where = f"{where}[{i}]"
        out.append(Fixture(
            text=_require(fx, "text", fx_where),
            expects=dict(_require(fx, "expects", fx_where)),
            surface=fx.get("surface"),
        ))
    return out


def parse_rule(d: dict[str, Any], where: str) -> Rule:
    rule_id = _require(d, "rule_id", where)
    fixtures = d.get("fixtures", {}) or {}
    return Rule(
        rule_id=rule_id,
        description=_require(d, "description", where),
        pattern=_parse_pattern(_require(d, "pattern", where), f"{where}({rule_id})"),
        severity=_parse_severity(_require(d, "severity", where), f"{where}({rule_id})"),
        canonical_sources=_parse_canonical_sources(
            _require(d, "canonical_sources", where), f"{where}({rule_id})"
        ),
        exceptions=_parse_exceptions(d.get("exceptions", []), f"{where}({rule_id})"),
        fixtures_positive=_parse_fixtures(
            list(fixtures.get("positive", [])), f"{where}({rule_id}).fixtures.positive"
        ),
        fixtures_negative=_parse_fixtures(
            list(fixtures.get("negative", [])), f"{where}({rule_id}).fixtures.negative"
        ),
    )


def parse_families(d: dict[str, Any]) -> dict[str, Family]:
    out: dict[str, Family] = {}
    for fam_name, fam_data in d.items():
        if not isinstance(fam_data, dict):
            continue
        ctx_tags_raw = fam_data.get("context_tags", {}) or {}
        ctx_tags: dict[str, re.Pattern[str]] = {}
        for tag, body in ctx_tags_raw.items():
            if isinstance(body, list):
                # Older TOML form: list of patterns ANDed via alternation.
                joined = "|".join(f"(?:{b})" for b in body)
                ctx_tags[tag] = _compile_regex(joined, [], f"_families.{fam_name}.context_tags.{tag}")
            else:
                ctx_tags[tag] = _compile_regex(str(body), [], f"_families.{fam_name}.context_tags.{tag}")
        extras = {k: v for k, v in fam_data.items() if k != "context_tags"}
        out[fam_name] = Family(name=fam_name, context_tags=ctx_tags, extras=extras)
    return out


def parse_surfaces(d: dict[str, Any]) -> SurfaceRegistry:
    roots = list(d.get("roots", []))
    surfaces = {k: list(v) for k, v in d.get("surfaces", {}).items()}
    return SurfaceRegistry(roots=roots, surfaces=surfaces)


# --- Path resolution (portable, no host hardcodes) ------------------------


def resolve_root(surfaces: SurfaceRegistry, library_path: Path) -> Path:
    """Walk ``surfaces.roots`` in declaration order. First that resolves wins.

    Resolution methods:
      * ``env = "VAR"`` — uses ``os.environ.get(VAR)`` if set and existing
      * ``relative_to_self = "../foo"`` — relative to the rule library dir
      * ``discover = {nearest_ancestor_with = "path/to/marker"}`` — walks
        upward from CWD looking for an ancestor where the marker resolves

    Raises RuleLibraryError if no root resolves.
    """
    for spec in surfaces.roots:
        if "env" in spec:
            val = os.environ.get(spec["env"])
            if val:
                p = Path(val).expanduser()
                if p.exists():
                    return p
        if "relative_to_self" in spec:
            p = (library_path / spec["relative_to_self"]).resolve()
            if p.exists():
                return p
        if "discover" in spec:
            disc = spec["discover"]
            marker = disc.get("nearest_ancestor_with")
            if marker:
                cur = Path.cwd().resolve()
                while True:
                    if (cur / marker).exists():
                        return cur
                    if cur.parent == cur:
                        break
                    cur = cur.parent
    raise RuleLibraryError(
        f"no root could be resolved from surfaces.roots ({len(surfaces.roots)} candidates tried)"
    )


# --- Library discovery + load ---------------------------------------------


DEFAULT_LIBRARY_ENV = "EVIDENCE_GATE_RULES_DIR"


def discover_library(start: Path | None = None) -> Path | None:
    """Locate a rule library directory.

    Search order:
      1. ``$EVIDENCE_GATE_RULES_DIR`` (must resolve to a directory if set;
         raises RuleLibraryError if set but missing — this is *configured*
         input, not auto-discovery)
      2. ``<start>/PROJECTS/arbiter/rules`` walking up from start
      3. ``<repo-root>/../arbiter/rules`` (sibling of hummbl-production)

    Returns the resolved Path, or None if no library is configured AND
    none is discovered by walking up. A None return means the caller may
    fall through to v1 hardcoded rules.

    Raising RuleLibraryError is reserved for two cases:
      * A library was *configured* (env var set) but cannot be resolved
      * A library was discovered but is malformed (raised by load_library)

    The env-var-set-but-missing case raises here. Codex Stage-3 PR #225
    P1 fix: previously this fell through to the ancestor walk, returning
    None and silently falling back to v1 — violating the guardrail that
    fallback is only allowed when nothing is discovered OR configured.
    """
    env = os.environ.get(DEFAULT_LIBRARY_ENV)
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p
        raise RuleLibraryError(
            f"{DEFAULT_LIBRARY_ENV}={env!r} is set but does not resolve to a directory; "
            "explicit configuration must be valid (no silent fallback)"
        )

    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        d = candidate / "PROJECTS" / "arbiter" / "rules"
        if d.is_dir():
            return d
        d = candidate / "arbiter" / "rules"
        if d.is_dir():
            return d
    return None


def load_library(library_path: Path) -> LoadedRules:
    """Load a rule library directory.

    Reads:
      - ``_surfaces.toml`` (required)
      - ``_families.toml`` (optional, defaults to {})
      - ``ER-*.toml`` (one rule per file)

    Raises RuleLibraryError if any file is malformed or required pieces missing.
    """
    if not library_path.is_dir():
        raise RuleLibraryError(f"{library_path}: not a directory")

    surfaces_path = library_path / "_surfaces.toml"
    if not surfaces_path.is_file():
        raise RuleLibraryError(f"{library_path}: missing required _surfaces.toml")
    surfaces = parse_surfaces(_load_toml(surfaces_path))

    families_path = library_path / "_families.toml"
    families = parse_families(_load_toml(families_path)) if families_path.is_file() else {}

    rules: list[Rule] = []
    for tomlf in sorted(library_path.glob("ER-*.toml")):
        rules.append(parse_rule(_load_toml(tomlf), where=str(tomlf)))

    if not rules:
        raise RuleLibraryError(
            f"{library_path}: no ER-*.toml rule files found (library would be empty)"
        )

    # Resolve root once at load time to surface bad path config early.
    surfaces.resolved_root = resolve_root(surfaces, library_path)

    return LoadedRules(
        rules=rules,
        families=families,
        surfaces=surfaces,
        library_path=library_path,
    )


def discover_and_load(start: Path | None = None) -> LoadedRules | None:
    """Discover a rule library and load it. Returns None if nothing is discovered.

    Distinguishes:
      - "no library found" -> returns None (caller may fall through to v1)
      - "library found but malformed" -> raises RuleLibraryError (caller should exit 2)
    """
    found = discover_library(start)
    if found is None:
        return None
    return load_library(found)


# --- git rev-parse policy (subprocess args, no shell, with timeout) -------


def verify_sha_ref(repo_root: Path, sha: str, timeout: float = 5.0) -> bool:
    """Return True iff ``sha`` resolves to a commit in ``repo_root``.

    Stdlib subprocess only. List args (no shell). Bounded timeout.
    Per Stage-2 schema codex answer #4.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


__all__ = [
    "Rule",
    "Pattern",
    "CompoundBranch",
    "Severity",
    "SeverityClause",
    "CanonicalSources",
    "Exception_",
    "Fixture",
    "Family",
    "SurfaceRegistry",
    "LoadedRules",
    "RuleLibraryError",
    "SEVERITY_ORDER",
    "demote_one_tier",
    "promote_to",
    "compute_severity",
    "classify_compound",
    "classify_broccolilly",
    "discover_library",
    "discover_and_load",
    "load_library",
    "parse_rule",
    "parse_families",
    "parse_surfaces",
    "resolve_root",
    "verify_sha_ref",
    "DEFAULT_LIBRARY_ENV",
]
