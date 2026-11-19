---
name: deploy-fly
description: Deploy, release or roll back Touchline on Fly.io, or set Fly secrets. Use when asked to ship, deploy, release, roll back or change production configuration.
---

Every step changes production, so get the user's explicit approval first for each deploy,
rollback, restart or secret change.

- **Normal path.** Merge the PR. `.github/workflows/deploy.yml` deploys `main` and checks
  `/health`. Watch it with `gh run list --workflow deploy` and `gh run view <id>`.
- **Manual deploy** (approved): `fly deploy --remote-only`, then
  `curl -fsS https://<app>.fly.dev/health`.
- **Rollback** (approved): find the last good image with `fly releases`, then
  `fly deploy --image registry.fly.io/<app>:<tag>`.
- **Secrets** (approved): `fly secrets set NAME=value` restarts the machine. Never echo secret
  values back in chat or logs.
- **First-time setup** is a human task; see `docs/features/deployment.md`.
