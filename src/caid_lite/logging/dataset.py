"""DatasetWriter: append-only JSONL log of every pipeline run.

Each successful or failed run produces one JSON record.  The file is named
``runs_YYYY-MM-DD.jsonl`` and lives in ``config.logging.log_dir``
(default: ``data/logs/``).

These logs serve three purposes:
  1. Debugging — full trace of every generation + repair attempt.
  2. Dataset collection — ``success=true`` records become (prompt, code) pairs
     for fine-tuning Qwen3-Coder.
  3. Benchmarking — ``batch_eval.py`` reads these to compute pass-rate metrics.

Phase 1 status: skeleton with ``write()`` interface defined.
Full integration with ``CADPipeline`` happens in Phase 3.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class DatasetWriter:
    """Appends one JSONL record per pipeline run.

    Args:
        log_dir: Directory where ``runs_YYYY-MM-DD.jsonl`` files are written.
            Created automatically if it does not exist.

    Example::

        writer = DatasetWriter(log_dir=Path("data/logs"))
        writer.write({"run_id": "abc", "success": True, "prompt": "a box", ...})
    """

    def __init__(self, log_dir: Path = Path("data/logs")) -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, record: Dict[str, Any]) -> Path:
        """Append a run record to today's JSONL file.

        Args:
            record: Arbitrary dict — must be JSON-serialisable.  Should at
                minimum contain ``run_id``, ``success``, ``prompt``, and
                ``elapsed_s``.

        Returns:
            Path to the JSONL file that was written.
        """
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        path = self._today_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return path

    def today_path(self) -> Path:
        """Return the path of today's log file (may not exist yet)."""
        return self._today_path()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today_path(self) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"runs_{date_str}.jsonl"
