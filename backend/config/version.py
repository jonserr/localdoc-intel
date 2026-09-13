"""Single source of truth for the application version served by the API.

Keep this in step with pyproject.toml, package.json, and
frontend/package.json. `python scripts/check_version_sync.py` verifies that,
and `--set X.Y.Z` rewrites all four.
"""

APP_VERSION = "1.1.0"
