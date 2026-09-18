"""FreeCycle backend.

The `agent` package lives beside `backend/` rather than inside it (it is a separate
deployable), so the repository root goes on sys.path here. That makes
`uvicorn app.main:app` work from this directory with no PYTHONPATH gymnastics; the
Dockerfile sets PYTHONPATH as well, and pytest adds it via pyproject.toml.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)
