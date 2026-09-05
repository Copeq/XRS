# AGENT.md

Repository collaboration guide for humans and coding agents working in this repo.

This file is intentionally practical. It explains how to approach the repo, where to look first, how to validate changes, and how to prepare a PR without exposing private workflow details.

## Purpose

- Keep contributors aligned on repo-specific workflow.
- Reduce repeated discovery when continuing prior work.
- Make PRs and validation steps predictable.

## First Principles

This document is the public repo-facing collaboration summary. It should be sufficient for contributors to work safely without relying on private local notes or environment-specific instructions.

Start from these rules:

- Check repository documentation before making changes.
- Check the current worktree before editing. Do not assume a clean tree.
- Continue in-progress work instead of rediscovering the repo from scratch when obvious local context exists.
- Preserve existing UI structure unless the task explicitly calls for redesign.
- Keep secrets, passwords, tokens, and private credentials out of tracked repo files.
- Do not commit local notes, private operational records, credentials, tokens, or environment-specific files.

## Repo Shape

High-level layout:

- `station_edition/`: primary base-station product and runtime.
- `frontend/`: local frontend build tooling; currently used for the shared home Vue bundle.
- `portable_edition/`: intentionally WIP / limited scope in the current workflow.
- `pytools/`: build helpers.
- `tools/`: local helper scripts.
- `tests/`: test assets and repo tests.

Key current architecture facts:

- Root `run.py` is a compatibility wrapper.
- Shared Station UI template lives in `station_edition/xrs/web_server.py`.
- The shared home page has a Vue bridge bundle at `/assets/vue/rid-home.js`.

## Working Rules

- Do not restart discovery if there is already in-progress work. Inspect current diffs and existing repo documentation first.
- Preserve the existing UI structure unless the task explicitly asks for a redesign.
- Prefer small, additive changes over wide rewrites when patching shared UI or parser logic.

## Current Workflow Notes

Current repo workflow, summarized:

- `station_edition/` is the main product runtime.
- Root `run.py` is compatibility glue, not the primary implementation surface.
- Shared Station UI template and much of the shared browser logic live in `station_edition/xrs/web_server.py`.
- The shared home page currently uses a Vue bundle at `station_edition/xrs/assets/vue/rid-home.js`, built from `frontend/`.

## Common Validation

Pick the smallest validation set that honestly covers the change. Typical commands:

### Python

```bash
python -m py_compile station_edition\xrs\web_server.py
```

### Shared home frontend bundle

```bash
cd frontend
npm run build:rid-home
cd ..
node --check station_edition\xrs\assets\vue\rid-home.js
```

### Diff hygiene

```bash
git diff --check
```

### Local HTTP smoke

Examples:

- Station default runtime: usually `http://127.0.0.1:4600/` when running locally

If changing browser behavior or shared UI:


## Deployment

- Deployment should follow the maintainer-approved private deployment runbook.
- Do not document environment-specific deployment commands, hosts, logs, or runtime checks in this public guide.
- Record deployment status in the PR only at a high level, without exposing private infrastructure or operational details.

## PR Guidance

A good PR for this repo should include:

- What changed in product terms, not just file terms.
- Any behavior inherited through `station_edition/xrs/web_server.py`.
- Validation commands actually run.
- Whether deployment was performed, at a high level if relevant.
- Any remaining risk, compatibility assumption, or intentionally deferred item.

Recommended PR structure:

1. Summary
2. Scope
3. Validation
4. Deploy status
5. Risks / follow-ups

If deployment was not run, say so explicitly.

If private maintainer notes exist outside the repo, do not reference them in public PR text.

## Handoff Expectations

When ending a non-trivial task, capture enough information for the next contributor to continue safely.

If maintainers use private local notes outside Git, treat them as non-public and do not rely on them in public documentation.

Minimum handoff content:

- files touched
- validation run
- deploy status
- known unresolved risks or assumptions

## UI-Specific Reminders

- The current iCloud-style restyle is broad and CSS-heavy in `station_edition/xrs/web_server.py`; inspect there first if visual regressions appear.
- The Station network binding editor now lives inline as `#network-bind-module` inside the settings capture card and is default-collapsed.

## Do Not Forget

- Check for existing uncommitted work before editing.
- Keep README and README.zh-CN aligned when changing user-facing docs.
- Keep deployment discussion high level in public repo artifacts.
