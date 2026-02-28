#!/usr/bin/env python3
"""Kvinde Klinikken AI Triage — Web UI entry point."""

import uvicorn

from triage.api import app  # noqa: F401

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
