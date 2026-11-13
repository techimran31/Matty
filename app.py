"""
app.py - entry point alias for Render's default Python start command.

Render's Python runtime defaults to `gunicorn app:app` when it cannot read a
start command from render.yaml. server.py holds the real Flask application, so
this module simply re-exports it. Having both names means the service boots
whether the start command comes from the blueprint or from auto-detection -
and it can never fall back to a Windows .bat file again.
"""

from server import app  # noqa: F401

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
