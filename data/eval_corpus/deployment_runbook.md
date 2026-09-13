# Deployment runbook

Before promoting a release to production, validate database migrations against
a copy of the production schema. Confirm that the cache layer answers a health
probe and that the queue worker consumes from the indexing queue.

Halt the promotion when any validation step fails. Attach the failing job logs
to the release ticket. The on-call engineer owns the rollback decision.

Rollback restores the previous container image and replays no migrations. A
migration that cannot be rolled back must ship in its own release.
