"""
Entry point for the AI Usage Dashboard.

Usage:
    python main.py
"""

from dashboard.app import app, server  # noqa: F401 — server exported for gunicorn/WSGI

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
