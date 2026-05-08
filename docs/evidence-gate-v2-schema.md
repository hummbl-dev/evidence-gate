# Evidence-Gate v2 Rule Library — Schema Receipt

This is the versioned schema receipt for the Evidence-Gate v2 rule library
accepted by codex at `2026-05-08T17:55:01Z` and implemented in
`hummbl-production` PR #225 (merged as `07047fe`).

This repo is the **canonical home** for the rule library. It mirrors to
GitHub (`hummbl-dev/evidence-gate`) and Gitea (`HUMMBL/evidence-gate`).

## Contract (v0.3)

- Rules are TOML files under `PROJECTS/evidence-gate/rules/`.
- `tomllib` is the parser. No PyYAML or third-party runtime dependency is
  allowed.
- One rule lives in one `ER-*.toml` file.
- Shared registry files are `_surfaces.toml` and `_families.toml`.
- Malformed configured libraries are hard `LOAD_ERROR` cases. Silent v1
  fallback is allowed only when no library is configured or discovered.
  This applies symmetrically across `--rules-dir`, `EVIDENCE_GATE_RULES_DIR`,
  and explicit `load_library(path)` calls.
- Host paths must be resolved by env var, sibling path, or ancestor discovery.
  Rules must not encode Anvil-, huxley-, or nodezero-specific absolute paths.

## Implemented Rules

- `ER-001-multiplier-no-source`
- `ER-002-numeric-with-unit-no-source` (Stage-3 P3 fix: now promotes external phantom → ERROR, symmetric with ER-006)
- `ER-003-code-ident`
- `ER-004-sha-ref`
- `ER-005-pr-ref`
- `ER-006-exact-percent`
- `ER-007-dated-incident` (Stage-3 P2 fix: scope changed from `family.date` to `roots.repo`)
- `ER-008-broccolilly-tuple`

Total: **8 rules, 32 fixtures** as of canonical-home migration.

## Fixture Harness

Run from `PROJECTS/evidence-gate`:

```powershell
python scripts\run_rule_fixtures.py
```

The harness imports the merged `hummbl-production/scripts/rule_loader.py`, loads
`rules/`, and executes every embedded fixture. It is intentionally stdlib-only.

## Fail-closed semantics for the third-PR find_claims rewrite (v0.3)

The third PR will rewrite `case_study_verify.find_claims_in_html` and
`find_claims_in_cases_json` to consume the loaded rule library directly,
replacing the v1 hardcoded patterns with rule-driven extraction. That
rewrite MUST inherit the fail-closed invariant established at the loader
layer in PR #225:

> When a configured rule library exists, every layer that consumes it
> MUST fail closed on unsupported / unrecognized / malformed input. The
> only legal silent-fallback path is "no library configured AND none
> discovered." Any other failure mode at any layer is exit 2 / ERROR /
> finding-emit, never a silent skip.

### Layer-by-layer fail-closed contract

| Layer | Failure mode | Behavior | Status |
|---|---|---|---|
| L1 — config discovery | `EVIDENCE_GATE_RULES_DIR` set but missing | `RuleLibraryError` → exit 2 | **Shipped PR #225 commit `750055a`** |
| L1 | `--rules-dir PATH` invalid | exit 2 | **Shipped PR #225 commit `b99bafc`** |
| L1 | No library configured AND no auto-discovery hit | Return None → v1 fallback | **Shipped PR #225 (only legal silent path)** |
| L2 — library load | `_surfaces.toml` missing from configured library | `RuleLibraryError` → exit 2 | **Shipped PR #225** |
| L2 | Any TOML in library malformed | `RuleLibraryError` → exit 2 | **Shipped PR #225** |
| L2 | Rule pattern fails to compile | `RuleLibraryError` → exit 2 | **Shipped PR #225** |
| L3 — rule execution | Rule has unsupported `pattern.kind` | **Must ERROR**, must NOT silent-skip | **Pending third PR** |
| L3 | Rule has unsupported `canonical_sources.policy` | **Must ERROR** | Pending third PR |
| L3 | Rule references unknown severity context | **Must ERROR or WARN-with-finding** | Pending third PR |
| L3 | Rule references a `family.<name>` not in `_families.toml` | **Must ERROR** | Pending third PR |
| L3 | Compound rule has branch with no classifier dispatch | **Must ERROR** | Pending third PR |
| L4 — finding emission | Surface classification can't be determined for a target | ERROR if target is in known repo but unmatched, WARN+default for free text | Pending third PR |

### Guidance for the third-PR author

1. Before adding any new rule field, classifier, or extractor branch,
   identify the L3 / L4 row that would govern its failure mode.
2. Write a fail-closed test FIRST.
3. Only after the fail-closed test passes, add the happy-path
   implementation.
4. If you find yourself writing `if not_supported: continue` or
   `else: return default_severity` anywhere in the extractor, stop and
   convert to `raise RuleSemanticsError` or emit a `Finding(severity=ERROR,
   pattern_kind="rule_semantics_unsupported")`.

## Cross-Check Trail

- Stage-1 PROPOSAL: `2026-05-08T16:47:27Z`, claude-code → codex.
- Stage-1 REVIEW: `2026-05-08T17:12:09Z`, codex approved direction with 3 P1
  and 1 P2 conditions.
- Stage-2 v0.1 BLOCKED: `2026-05-08T17:45:49Z`, codex blocked YAML, phantom
  percentage demotion, Broccolilly fixture mismatch, and non-versioned schema.
- Stage-2 v0.2 ACK: `2026-05-08T17:55:01Z`, codex accepted TOML/tomllib,
  context-tag percentage handling, post-match Broccolilly classification, and
  versioned landing surface.
- Stage-3 REVIEW: `2026-05-08T18:26:21Z`, codex blocked PR #225 on env-var
  silent fallback.
- Stage-3 RE-REVIEW: `2026-05-08T18:32:14Z`, codex approved PR #225 after
  fix `750055a`.
- PR #225 merged: `2026-05-08T18:36:09Z`, merge commit `07047fe`.
- Codex (c)+(d) TASK_COMPLETE: `2026-05-08T18:40:51Z`, 8 rules + harness +
  schema receipt + README. 31 fixtures pass against merged loader.
- AAR pair (claude-code + codex): `2026-05-08T18:42:09Z` + `18:44:15Z`.
- Steward Stage-3 review of (c)+(d) (claude-code → codex): `2026-05-08T19:12:45Z`
  + second-pass `19:18:42Z`. APPROVE direction with 1 P2 (ER-007 family.date)
  + 5 P3 (ER-002 asymmetry; schema receipt timeline; basis-required permissive;
  compound dispatch silent fallback; fixture reason decorative).
- Operator decision on canonical home: `2026-05-08T20:11Z` — chose Option B
  (rename to `hummbl-dev/evidence-gate`, separate from older
  `hummbl-dev/arbiter` code-quality scoring project).
- This receipt + the P2 + P3#1 fixes apply at v0.3 (canonical-home migration).

## Related artifacts

- `~/.agents/rules/cross-check-discipline.md` — author-side cross-check
  discipline (Implementer's-Bar Self-Grill, Symmetric Configuration-Path
  Coverage, Gating-Class Positive Test First).
- `~/.claude/projects/.../memory/feedback_estimation_decomposition.md` —
  estimation-decomposition rule, originated 2026-05-08 from the same lane.
