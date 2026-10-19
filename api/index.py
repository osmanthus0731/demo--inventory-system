"""Vercel entry point for the self-contained fictional demonstration."""

from pathlib import Path
import sys


# Keep imports reliable when Vercel loads this file from the ``api`` directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_demo import module


# Vercel discovers WSGI applications exposed as ``app``.
app = module.app
