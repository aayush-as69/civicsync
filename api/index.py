"""Vercel serverless entrypoint: exposes the Flask app from backend/app.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import app  # noqa: E402,F401  (Vercel looks for a WSGI object named `app`)
