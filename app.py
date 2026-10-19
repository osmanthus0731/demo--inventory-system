"""Public entry point for the isolated fictional inventory demo.

Vercel's Flask preset discovers this root module automatically. The bootstrap
uses the configured demo database (or local in-memory preview) and disables Access.
"""

from run_demo import module


app = module.app
