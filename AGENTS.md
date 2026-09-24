# Touchline agent workflow

## Code changes

Use the Ponytail plugin in **full** mode for every coding task: additions,
refactors, fixes, reviews, and technical design. Read the affected flow first,
then apply its ladder: avoid unnecessary work, reuse existing code, prefer the
standard library and native platform features, and make the smallest correct
change. Do not simplify security, validation, accessibility, or explicit
requirements away.

Before committing a code change:

1. Run the relevant checks (normally `.pythonenv/bin/python -m pytest -q`).
2. Update the matching `docs/features/` page; update `README.md` when setup or
   user-facing behaviour changes.
3. Fetch `origin/main` and simulate its merge with the task branch using
   `git merge-tree --write-tree HEAD origin/main`. If Git reports conflicts,
   rebase onto `origin/main`, resolve the conflicts locally, and rerun the
   relevant checks before staging.
4. Confirm `git status --short` and stage only files belonging to the change.
5. Work on a dedicated `codex/<brief-name>` branch, never directly on `main`,
   and create one focused commit.
6. Push the branch with `git push -u origin HEAD`, then create its pull request
   with `gh pr create --base main --fill` (or confirm the branch already has an
   open PR). A code task is not complete until it has an open PR; do not merge
   the PR or push directly to `main` unless the user explicitly asks.

Do not add unrelated working-tree changes to the commit. In the completion
message, name the test command, commit SHA, and documentation updated. Local
hooks and GitHub Actions enforce documentation and tests, but cannot prove an
agent followed Ponytail's reasoning; keep the resulting diff small and
reviewable.

## Parallel worktrees

For concurrent coding tasks, work only in the task's assigned Git worktree and
branch. Do not use the primary checkout for an isolated task, commit directly
to `main`, or merge another task's branch. Give each task a dedicated branch
using the `codex/` prefix; leave branch integration to the user or a designated
integration task. Before work starts, assign each task exclusive files or a
vertical slice; agree shared API, schema, type, and configuration changes
first. The integration task owns cross-cutting files such as shared routes,
dependency manifests, migrations, and release configuration. Avoid unrelated
formatting or refactoring while parallel work is active. Re-run the merge
simulation before push or whenever `origin/main` advances; resolve any detected
conflicts in the task branch locally.

## Documentation

`README.md` is the short product and setup entry point. `docs/features/` holds
feature guides; add a guide for a new meaningful capability and update its
guide whenever that capability changes. `docs/engineering-workflow.md`
explains the development safeguards.

## Production support

For a production-support request, inspect the public API health endpoints
first, then Railway status and sanitized logs when the Railway CLI is
available. Diagnose from evidence and report findings, but never deploy,
restart, roll back, alter variables or secrets, or access/reset production
data without the user's explicit approval. The push-triggered GitHub Actions
check is read-only and validates public behaviour only.
