# Production support

Pushes to `main` run a GitHub Actions check after Railway's normal continuous
deployment begins. The workflow polls the public API for up to ten minutes and
records its result in the job summary, allowing the engine's normal five-minute
cycle to complete. With the protected GitHub environment's Railway project
token, it also rejects recent structured application failures and traceback
signatures in API or engine logs. The optional token is made available to the
job as an environment variable so the log and artifact steps can be skipped
safely when it is absent.

It requires the API and engine health endpoints to return success, and requires
the summary endpoint to report paper mode, a running engine, a newly completed
engine cycle, and an Odds API key configured in both running processes. It
cannot repair production.
Update the public URL in the GitHub Actions workflow if the Railway domain
changes.

For an on-demand investigation, ask a Codex agent for production support. It
will inspect public health first and may use local Railway status/log access
when available. Any deployment, restart, rollback, configuration change, or
production-data action requires explicit approval.
