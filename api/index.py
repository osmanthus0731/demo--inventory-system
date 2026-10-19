"""Vercel entry point for the self-contained fictional demonstration."""

from run_demo import module


# Vercel discovers WSGI applications exposed as ``app``.
app = module.app
