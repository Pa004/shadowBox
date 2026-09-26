"""Cloudflare Python Worker entry (M4b scaffold).

Local emulation (no account needed):
    uvx --from workers-py pywrangler dev

Production additionally needs:
    1. `wrangler d1 create shadowbox` -> paste database_id into wrangler.jsonc
    2. `wrangler d1 execute shadowbox --file schema.sql`
    3. D1-backed store swap (same Store signatures, D1 binding instead of
       sqlite3 file) — follow-up task, needs account access to verify.
"""

try:
    from workers import asgi
except ImportError as exc:
    raise RuntimeError(
        "workers runtime missing: run inside `pywrangler dev`, not plain python"
    ) from exc

from shadowbox.api import create_app

# No store: each request builds a D1Store from the Worker's DB binding.
Default = asgi.entrypoint(create_app())
