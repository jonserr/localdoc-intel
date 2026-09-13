# Backup schedule

The primary database takes a full snapshot every night at 02:00 UTC and keeps
incremental write-ahead log segments for seven days.

Object storage replicates to a second region once per hour. Restore drills run
on the first Monday of each quarter.

A restore drill that exceeds four hours counts as a failure and opens a
follow-up ticket.
