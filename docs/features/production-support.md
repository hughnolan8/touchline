# Production support

Pushes to `main`, including merged pull requests, run the GitHub Actions
production workflow. It deploys the API and engine to Railway before polling
the public API for up to ten minutes and recording its result in the job
summary, allowing the engine's normal five-minute cycle to complete. With the
protected GitHub environment's Railway project token, it also rejects recent
structured application failures and traceback signatures in API or engine
logs. The optional token is made available to the job as an environment
variable so the log and artifact steps can be skipped safely when it is absent.

It requires the API and engine health endpoints to return success, and requires
the summary endpoint to report paper mode, a running engine, a newly completed
engine cycle, and an Odds API key configured in both running processes. It
cannot repair production.
Update the public URL in the GitHub Actions workflow if the Railway domain
changes.

## Service logs

The API and engine emit compact JSON events to Railway logs. They record API
method, path, status and duration; service lifecycle; engine-cycle outcomes;
provider request failures; and refresh jobs. Query strings, request bodies,
headers, provider URLs, and error messages are never logged, protecting
deployment and provider credentials. Postgres is Railway-managed and retains
its platform-managed database logs.

Engine failure events also include the safe workflow phase and exception type,
so operator logs identify the failing subsystem without exposing exception
messages or stored data.
Invalid bootstrap progress is identified by league and setting key, never by
the stored value.
Malformed stored match statistics are quarantined and rebuilt from the active
provider record; logs identify the affected match only.
An invalid Understat response is logged by league and skipped without advancing
bootstrap progress, so the next engine cycle can retry it.

For an on-demand investigation, ask a Codex agent for production support. It
will inspect public health first and may use local Railway status/log access
when available. Any deployment, restart, rollback, configuration change, or
production-data action requires explicit approval.
