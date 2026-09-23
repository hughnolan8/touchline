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
3. Confirm `git status --short` and stage only files belonging to the change.
4. Create one focused commit and run `git push origin main`.

Do not add unrelated working-tree changes to the commit. In the completion
message, name the test command, commit SHA, and documentation updated. Local
hooks and GitHub Actions enforce documentation and tests, but cannot prove an
agent followed Ponytail's reasoning; keep the resulting diff small and
reviewable.

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
