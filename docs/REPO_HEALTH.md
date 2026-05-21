# Repository Health Contract

## Identity

- **Repository**: `HUMMBL/evidence-gate`
- **Canonical host**: `https://anvil.tail0ff7b3.ts.net/HUMMBL/evidence-gate`
- **GitHub peer**: `https://github.com/hummbl-dev/evidence-gate`
- **Visibility**: Public
- **Default branch**: `main`
- **Owner**: HUMMBL Team

## Lifecycle

- **Status**: Active private evidence verification library
- **Purpose**: Curate and test rule definitions used by HUMMBL pre-publish source-verification tooling.

## Canonical Relationship

- **Gitea posture**: Active validation surface, not a read-only mirror.
- **Source of truth**: the maintained Anvil working tree at `C:\Users\Owner\PROJECTS\evidence-gate`, published to Gitea and GitHub.
- **GitHub relationship**: peer publication surface for downstream consumers and historical continuity.
- **Scope**: Rules and fixtures are authoritative only for evidence posture tooling; claims quality and publishing governance remain review decisions.

## Validation Contract

From repository root:

```bash
python scripts/run_rule_fixtures.py
```

For fixture consumption against case studies:

```bash
EVIDENCE_GATE_RULES_DIR="$PWD/rules" python ../hummbl-production/scripts/case_study_verify.py path/to/case-study.html
```

## Branch Protection Expectation

- Protect `main` with review-first intake for non-trivial rule changes.
- Required checks should include fixture pass and TOML parseability on touched rule files.
