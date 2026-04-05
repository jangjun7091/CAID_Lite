"""DatasetWriter: append-only JSONL log of every pipeline run.

Each successful or failed run produces one JSON record.  The file is named
``runs_YYYY-MM-DD.jsonl`` and lives in ``config.logging.log_dir``
(default: ``data/logs/``).

These logs serve three purposes:
  1. Debugging — full trace of every generation + repair attempt.
  2. Dataset collection — ``success=true`` records become (prompt, code) pairs
     for fine-tuning Qwen3-Coder / other code LLMs.
  3. Benchmarking — ``batch_eval.py`` reads these to compute pass-rate metrics.

Golden samples
--------------
A "golden sample" is a run that succeeded on the **first attempt** (zero repair
iterations).  These represent the highest-quality (prompt, code) pairs and are
stored separately in ``golden_samples.jsonl`` alongside the daily run files.

Fine-tuning export
------------------
``DatasetWriter.export_finetune()`` reads all ``runs_*.jsonl`` files (or a
provided list) and writes a new JSONL file in the OpenAI fine-tuning format::

    {"messages": [
        {"role": "system",  "content": "<system_generate prompt>"},
        {"role": "user",    "content": "<original user prompt>"},
        {"role": "assistant","content": "```python\\n<final_code>\\n```"}
    ]}

Only records with ``success=true`` and non-empty ``generated_code`` are exported.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# System prompt injected into every fine-tune sample so the model learns the
# correct generation context.  Kept short to save tokens; the full
# system_generate.txt is used at inference time.
_FINETUNE_SYSTEM = (
    "You are an expert CadQuery programmer. "
    "Generate a build_model() function that creates the described 3D geometry "
    "and returns a cq.Workplane object. "
    "Return ONLY Python code inside a ```python code block."
)


class DatasetWriter:
    """Appends one JSONL record per pipeline run and exports fine-tune datasets.

    Args:
        log_dir: Directory where ``runs_YYYY-MM-DD.jsonl`` and
            ``golden_samples.jsonl`` are written.
            Created automatically if it does not exist.

    Example::

        writer = DatasetWriter(log_dir=Path("data/logs"))
        writer.write(result.to_dict())
        # After a first-attempt success:
        writer.write_golden(result.to_dict())
        # Export all successes as fine-tuning JSONL:
        writer.export_finetune(Path("data/finetune/ft_dataset.jsonl"))
    """

    _GOLDEN_FILENAME = "golden_samples.jsonl"

    def __init__(self, log_dir: Path = Path("data/logs")) -> None:
        self._log_dir = Path(log_dir)
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

    def write_golden(self, record: Dict[str, Any]) -> Path:
        """Append a golden sample record to the shared ``golden_samples.jsonl``.

        A golden sample is a first-attempt success (``repair_iterations == 0``
        or no repair field).  The caller is responsible for deciding whether
        a record qualifies — this method simply writes it to the golden file.

        Args:
            record: A ``PipelineResult.to_dict()`` for a successful, zero-repair run.
                Will have ``"_golden": true`` injected automatically.

        Returns:
            Path to ``golden_samples.jsonl``.
        """
        record = dict(record)  # shallow copy — do not mutate caller's dict
        record["_golden"] = True
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        path = self._golden_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return path

    def export_finetune(
        self,
        output_path: Path,
        source_files: Optional[List[Path]] = None,
        system_prompt: str = _FINETUNE_SYSTEM,
        golden_only: bool = False,
    ) -> int:
        """Export successful pipeline runs as an OpenAI-compatible fine-tune JSONL.

        Each output line is a ``{"messages": [...]}`` object with three turns:
        system / user / assistant.  The assistant turn wraps the final code in
        a ````python`` fence so the model learns the expected output format.

        Args:
            output_path: Destination ``.jsonl`` file (created or overwritten).
            source_files: Explicit list of source JSONL files to read.  When
                ``None``, all ``runs_*.jsonl`` files in ``log_dir`` are used.
                ``golden_samples.jsonl`` is always included unless
                ``source_files`` is specified explicitly.
            system_prompt: System turn injected into every sample.
            golden_only: When ``True``, only export records that have
                ``"_golden": true`` (i.e. first-attempt successes).

        Returns:
            Number of samples written.
        """
        if source_files is None:
            source_files = sorted(self._log_dir.glob("runs_*.jsonl"))
            golden = self._golden_path()
            if golden.is_file() and golden not in source_files:
                source_files.append(golden)

        records = _load_records(source_files)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        seen_run_ids: set = set()

        with output_path.open("w", encoding="utf-8") as out:
            for rec in records:
                # De-duplicate by run_id
                run_id = rec.get("run_id", "")
                if run_id and run_id in seen_run_ids:
                    continue
                if run_id:
                    seen_run_ids.add(run_id)

                if not rec.get("success", False):
                    continue
                if golden_only and not rec.get("_golden", False):
                    continue

                code = rec.get("generated_code", "").strip()
                prompt = rec.get("prompt", "").strip()
                if not code or not prompt:
                    continue

                sample = {
                    "messages": [
                        {"role": "system",    "content": system_prompt},
                        {"role": "user",      "content": prompt},
                        {"role": "assistant", "content": f"```python\n{code}\n```"},
                    ]
                }
                out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                written += 1

        return written

    def today_path(self) -> Path:
        """Return the path of today's log file (may not exist yet)."""
        return self._today_path()

    def golden_path(self) -> Path:
        """Return the path of the golden samples file (may not exist yet)."""
        return self._golden_path()

    def count_golden(self) -> int:
        """Return the number of records in ``golden_samples.jsonl``."""
        path = self._golden_path()
        if not path.is_file():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today_path(self) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"runs_{date_str}.jsonl"

    def _golden_path(self) -> Path:
        return self._log_dir / self._GOLDEN_FILENAME


# ---------------------------------------------------------------------------
# Module-level helpers (used by export_finetune and scripts)
# ---------------------------------------------------------------------------

def _load_records(files: List[Path]) -> List[Dict[str, Any]]:
    """Read JSONL records from a list of files, silently skipping bad lines."""
    records: List[Dict[str, Any]] = []
    for path in files:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records
