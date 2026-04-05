"""Export pipeline run logs as an OpenAI-compatible fine-tuning JSONL.

Usage
-----
# Export all successful runs from data/logs/ to data/finetune/ft_dataset.jsonl
python scripts/export_finetune.py

# Export golden samples only (zero repair-iteration successes)
python scripts/export_finetune.py --golden-only

# Custom source and destination
python scripts/export_finetune.py \\
    --log-dir data/logs \\
    --output  data/finetune/my_dataset.jsonl

# Print stats only (dry run)
python scripts/export_finetune.py --dry-run

Output format (one JSON object per line)
-----------------------------------------
{"messages": [
    {"role": "system",    "content": "<system prompt>"},
    {"role": "user",      "content": "<original user prompt>"},
    {"role": "assistant", "content": "```python\\n<final CadQuery code>\\n```"}
]}

This format is directly compatible with:
  - OpenAI fine-tuning API  (openai.FineTuningJob.create)
  - Qwen3-Coder fine-tuning (DashScope training jobs)
  - Any framework accepting the OpenAI chat fine-tune format
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve src/ so this script works without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from caid_lite.logging.dataset import DatasetWriter, _load_records


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export CAID_Lite run logs to fine-tuning JSONL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--log-dir",
        default="data/logs",
        help="Directory containing runs_*.jsonl log files (default: data/logs)",
    )
    p.add_argument(
        "--output",
        default="data/finetune/ft_dataset.jsonl",
        help="Output JSONL file path (default: data/finetune/ft_dataset.jsonl)",
    )
    p.add_argument(
        "--golden-only",
        action="store_true",
        help="Export only golden samples (first-attempt successes, _golden=true)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count exportable records without writing output",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    log_dir = Path(args.log_dir)
    output = Path(args.output)

    writer = DatasetWriter(log_dir=log_dir)

    # Collect source files
    source_files = sorted(log_dir.glob("runs_*.jsonl"))
    golden = log_dir / DatasetWriter._GOLDEN_FILENAME
    if golden.is_file() and golden not in source_files:
        source_files.append(golden)

    if not source_files:
        print(f"[export_finetune] No log files found in {log_dir}", file=sys.stderr)
        sys.exit(0)

    # Count stats
    records = _load_records(source_files)
    total = len(records)
    successful = sum(1 for r in records if r.get("success", False))
    golden_count = sum(1 for r in records if r.get("_golden", False))
    exportable = golden_count if args.golden_only else successful

    print(f"[export_finetune] Log directory : {log_dir.resolve()}")
    print(f"[export_finetune] Source files  : {len(source_files)}")
    print(f"[export_finetune] Total records : {total}")
    print(f"[export_finetune] Successful    : {successful}")
    print(f"[export_finetune] Golden        : {golden_count}")
    print(f"[export_finetune] To export     : {exportable} ({'golden only' if args.golden_only else 'all successful'})")

    if args.dry_run:
        print("[export_finetune] Dry run — no output written.")
        return

    written = writer.export_finetune(
        output_path=output,
        source_files=source_files,
        golden_only=args.golden_only,
    )

    print(f"[export_finetune] Written       : {written} samples")
    print(f"[export_finetune] Output file   : {output.resolve()}")


if __name__ == "__main__":
    main()
