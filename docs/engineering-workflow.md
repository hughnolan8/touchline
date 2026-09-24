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

   Pytest reports line coverage for `backend` and lists missed lines. Review
   material gaps in application behaviour and add focused, deterministic tests
   with the change; do not add a percentage gate until the suite has a stable
   baseline.

3. Fetch `origin/main` and simulate its merge with the task branch:

   ```sh
   git fetch origin main
   git merge-tree --write-tree HEAD origin/main
   ```

   A non-zero result means the branches would conflict. Rebase onto
   `origin/main`, resolve the conflict in the task branch, and rerun the
   relevant checks before staging. Repeat this simulation before pushing and
   whenever `origin/main` advances.

4. Review `git status --short`, stage only the completed change, then make one
   focused commit on a `codex/**` task branch. Push it with `git push -u origin
   HEAD` and run `gh pr create --base main --fill` unless the branch already
   has an open pull request. Staging validates the pull request before it can
   merge to `main`; agents do not merge it themselves.

## Parallel work

Give every concurrent task its own worktree and `codex/**` branch. Before work
starts, divide the work into exclusive files or vertical slices, and agree any
shared API, schema, type, or configuration changes. Assign one integration task
to cross-cutting files such as shared routes, dependency manifests, migrations,
and release configuration. Keep commits focused and avoid unrelated formatting
or refactoring while parallel work is active. If the merge simulation finds a
conflict, resolve it locally in the task branch rather than leaving it for
integration.

Use `scripts/install-git-hooks.sh` once per clone to enable the local safety
net. The pre-commit hook requires a Markdown update in `README.md` or `docs/`
when application code is staged. The pre-push hook runs pytest. GitHub Actions
runs the same documentation rule and test suite for release branches, pull
requests, and `main`. A passing release branch is deployed to shared staging;
only the newest release branch retains that slot. See
[CI/CD](features/ci-cd.md) for the deployment gate.

The checks can demonstrate the test and documentation requirements, but no
automated check can prove an agent applied Ponytail's reasoning. The durable
evidence is a small, reviewable diff and the workflow recorded in the commit.

## Feature documentation

Keep `README.md` concise. Document each meaningful capability under
[`docs/features/`](features/README.md). Update the relevant feature page for
behaviour, data-source, model, or operational changes, and update the README
only when the user-facing setup or product overview changes.
