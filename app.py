"""Public entry point for the isolated fictional inventory demo.

Vercel's Flask preset discovers this root module automatically. The bootstrap
uses only in-memory fictional data and deliberately disables live integrations.
"""

from run_demo import module


app = module.app
