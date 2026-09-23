# Production support

Pushes to `main` run a read-only GitHub Actions check after Railway's normal
continuous deployment begins. The check polls the public API for up to ten
minutes and records its result in the workflow job summary.

It requires the API and engine health endpoints to return success, and requires
the summary endpoint to report paper mode, a running engine, and a newly
completed engine cycle. It has no Railway or OpenAI credentials, so it cannot
confirm a deployment's commit, inspect Railway logs, or repair production.

For an on-demand investigation, ask a Codex agent for production support. It
will inspect public health first and may use local Railway status/log access
when available. Any deployment, restart, rollback, configuration change, or
production-data action requires explicit approval.
