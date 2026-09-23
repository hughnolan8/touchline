# Engineering workflow

Every Touchline code task follows the repository instructions in `AGENTS.md`.
They require the Ponytail plugin in full mode: understand the affected flow,
then choose the smallest correct solution by preferring deletion, existing
code, the standard library, and native platform features over new abstractions
or dependencies.

## Change lifecycle

1. Make the focused implementation change and its feature-documentation update.
2. Run the relevant checks; the usual full suite is:

   ```sh
   .pythonenv/bin/python -m pytest -q
   ```

3. Review `git status --short`, stage only the completed change, then make one
   focused commit and push it to `main`.

Use `scripts/install-git-hooks.sh` once per clone to enable the local safety
net. The pre-commit hook requires a Markdown update in `README.md` or `docs/`
when application code is staged. The pre-push hook runs pytest. GitHub Actions
runs the same documentation rule and test suite for pushes to `main` and pull
requests.

The checks can demonstrate the test and documentation requirements, but no
automated check can prove an agent applied Ponytail's reasoning. The durable
evidence is a small, reviewable diff and the workflow recorded in the commit.

## Feature documentation

Keep `README.md` concise. Document each meaningful capability under
[`docs/features/`](features/README.md). Update the relevant feature page for
behaviour, data-source, model, or operational changes, and update the README
only when the user-facing setup or product overview changes.
