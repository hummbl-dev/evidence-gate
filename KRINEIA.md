# KRINEIA.md — evidence-gate

**krineia_manifest_version:** 0.1
**schema:** krineia-manifest@0.1

This is the repo-local KRINEIA manifest for `hummbl-dev/evidence-gate`. It declares how this repo participates in KRINEIA governance.

---
krineia_manifest_version: "0.1"
schema: "krineia-manifest@0.1"

repo:
  full_name: "hummbl-dev/evidence-gate"
  default_branch: "main"
  visibility: "public"

authority:
  steward: "HUMMBL Research Institute"
  approving_human: "Reuben Bowlby"
  source_of_record: "git"
  receipt_authority: "external_observer"

governance_profile:
  status: "adopted"
  krineia_required: true
  trust_root_mode: "deployment_asserted"
  receipt_chain_required_for:
    - "canonical_docs"
    - "authority_changes"

chains:
  primary:
    chain_id: "evidence-gate-primary"
    storage: "_receipts/krineia/primary.jsonl"
    genesis_policy: "repo_bootstrap"
    hash_algorithm: "sha256"
    canonicalization: "json.dumps(sort_keys=True,separators=(',',':'))"

operators:
  allowed:
    - "append"
    - "project"
    - "cut"
  forbidden:
    - "update"
    - "delete"
    - "rewrite"
    - "summarize_and_replace"
    - "score_and_train"

boundaries:
  no_reward_path_self_reference: true
  external_analysis_only: true
  observed_agent_may_write_receipts: false
  receipts_may_train_agents: false

verification:
  validator: "external"
  required_before_merge: false
  required_before_release: false

related_docs:
  readme: "README.md"

last_reviewed: "2026-06-23"
---

## Notes

### Archived repo

This repo is archived. Per HUMMBL Repo Standard §5.5, archived repos carry whatever they had at archival. This KRINEIA manifest was backfilled on 2026-06-23 for historical completeness, not because new work is expected.

### Chain bootstrapping

The primary chain at `_receipts/krineia/primary.jsonl` is bootstrapped with a genesis receipt recording the adoption of this manifest.
