# AGENTS.md — evidence-gate

## Project

**evidence-gate** — Pre-publish source-verification rule library for HUMMBL governance content. Stdlib-only TOML rules + fixture harness consumed by `hummbl-production/scripts/case_study_verify.py`. Python 3.11+ (uses `tomllib`), zero third-party runtime dependencies.

## Scope

- In scope: 8 ER-NNN TOML rules (`rules/`), surface registry (`_surfaces.toml`), context-tag families (`_families.toml`), stdlib fixture harness (`scripts/run_rule_fixtures.py`), v0.3 schema documentation, append-only review-learning corpus (`contribution_learnings.jsonl`)
- Out of scope: Consumer-side claim finding (lives in `hummbl-production`), publishing readiness judgments (human/agent review), broad content review

## Setup

```bash
git clone https://github.com/hummbl-dev/evidence-gate.git && cd evidence-gate
# No install needed — stdlib only, run scripts directly
```

## Testing

```bash
# Run fixtures locally (32 fixtures across 8 rules)
python scripts/run_rule_fixtures.py

# With explicit loader path (for hummbl-production consumer)
python scripts/run_rule_fixtures.py --rule-loader-path ../hummbl-production

# CI mode (skip missing private loader)
python scripts/run_rule_fixtures.py --skip-missing-loader
```

Full fixture execution depends on the private `hummbl-production/scripts/rule_loader.py` contract. Set `HUMMBL_PRODUCTION_ROOT` or pass `--rule-loader-path`.

## Conventions

- Python 3.11+ required (uses `tomllib`)
- Zero third-party runtime dependencies — no PyYAML; loader is `tomllib`, harness is stdlib `re` + `subprocess` + `pathlib`
- Each rule TOML declares: `[pattern]`, `[severity]` (default/promote_when/demote_when), `[canonical_sources]` policy, `[[exceptions]]`, embedded `[[fixtures.positive]]` / `[[fixtures.negative]]`
- Fail-closed contract: rules load + validate but don't yet drive findings (v1 hardcoded patterns still active in consumer)
- Commit format: Conventional Commits
- Branch naming: `type/agent/short-desc`
- Apache 2.0 license

## CI

GitHub Actions (`.github/workflows/`) + Gitea mirror (`.gitea/workflows/`). CI compiles `run_rule_fixtures.py` and parses rule TOML on supported Python versions when rule, script, schema-doc, or workflow files change. Uses `--skip-missing-loader` so public syntax checks run without access to the private loader repository.
