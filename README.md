# Evidence-Gate

Pre-publish source-verification rule library for HUMMBL governance content.

This repo is the **canonical home** for the Evidence-Gate v2 rule library
consumed by `hummbl-production/scripts/case_study_verify.py` and other
consumers. The canonical working tree lives on Anvil at
`PROJECTS/evidence-gate/`; this repo mirrors to GitHub
(`hummbl-dev/evidence-gate`) and Gitea (`HUMMBL/evidence-gate`).

## Layout

```
evidence-gate/
├── rules/                              # 8 ER-NNN.toml rules + _surfaces + _families
│   ├── _surfaces.toml                  # surface registry (external/internal/canonical-corpus globs)
│   ├── _families.toml                  # context-tag families (numeric, percent, broccolilly)
│   ├── ER-001-multiplier-no-source.toml
│   ├── ER-002-numeric-with-unit-no-source.toml
│   ├── ER-003-code-ident.toml
│   ├── ER-004-sha-ref.toml
│   ├── ER-005-pr-ref.toml
│   ├── ER-006-exact-percent.toml
│   ├── ER-007-dated-incident.toml
│   └── ER-008-broccolilly-tuple.toml
├── docs/
│   └── evidence-gate-v2-schema.md      # versioned schema receipt (v0.3)
├── scripts/
│   └── run_rule_fixtures.py            # stdlib fixture harness
├── contribution_learnings.jsonl        # append-only review-learning corpus
└── README.md
```

## Quickstart

```bash
# Run fixtures locally
cd PROJECTS/evidence-gate
python scripts/run_rule_fixtures.py
# → PASS: 32 fixtures across 8 rules

# Use against case studies via the consumer in hummbl-production
EVIDENCE_GATE_RULES_DIR="$PWD/rules" python ../hummbl-production/scripts/case_study_verify.py path/to/case-study.html
```

## How rules work

Each rule is a TOML file that declares:

- A `[pattern]` (regex / phrase / compound) that finds candidate claims in text
- `[severity]` rules — `default`, `promote_when` contexts, `demote_when` contexts
- `[canonical_sources]` policy — `must_match_with_unit` / `must_match_anywhere` /
  `must_match_full_context` / `git_rev_parse` / `none`
- `[[exceptions]]` — marker matches like `[VERIFY: <basis>]` that demote-by-one-tier
- Embedded `[[fixtures.positive]]` and `[[fixtures.negative]]` — test cases the
  harness validates on every run

See `docs/evidence-gate-v2-schema.md` for the full v0.3 schema, the layer-by-layer
fail-closed contract, and the cross-check trail.

## Status

- v0.3 (current): canonical-home migration. ER-007 family.date P2 fix applied;
  ER-002 P3 alignment with ER-006 (external phantom → ERROR).
- 8 rules / 32 fixtures all pass against `hummbl-production` `rule_loader.py`
  on `main` (commit `07047fe`+).
- Pending **third PR** in `hummbl-production`: rewire `find_claims_in_html` to
  consume rules directly (currently uses v1 hardcoded patterns; rule library
  loads + validates but doesn't yet drive findings).

## Stdlib only

No PyYAML, no third-party runtime dependencies. Loader is `tomllib` (Python
3.11+). Harness is stdlib `re` + `subprocess` + `pathlib`.

## Origin

Authoring split (codex c+d after claude-code Stage-2 schema + (b) loader).
See `docs/evidence-gate-v2-schema.md` § Cross-Check Trail for the full
multi-stage history with bus receipts.

## Repository Health

See [REPO_HEALTH.md](docs/REPO_HEALTH.md) for the authoritative repository
health contract, validation commands, and branch-protection expectations.
