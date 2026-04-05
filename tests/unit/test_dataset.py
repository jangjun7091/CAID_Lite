"""Tests for DatasetWriter golden sample collection and fine-tune export.

All tests use tmp_path — no production data is read or written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caid_lite.logging.dataset import DatasetWriter, _load_records


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _record(
    run_id: str = "abc123",
    success: bool = True,
    prompt: str = "a box",
    code: str = "import cadquery as cq\ndef build_model():\n    return cq.Workplane('XY').box(1,1,1)",
    repair_iterations: int = 0,
    golden: bool = False,
) -> dict:
    r = {
        "run_id": run_id,
        "success": success,
        "prompt": prompt,
        "generated_code": code,
        "repair": {"iterations": repair_iterations, "repaired": repair_iterations > 0},
        "elapsed_s": 1.0,
    }
    if golden:
        r["_golden"] = True
    return r


# ── DatasetWriter.write() ─────────────────────────────────────────────────────


class TestDatasetWriterWrite:
    def test_creates_log_dir(self, tmp_path):
        log_dir = tmp_path / "nested" / "logs"
        writer = DatasetWriter(log_dir=log_dir)
        writer.write(_record())
        assert log_dir.is_dir()

    def test_creates_daily_file(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        path = writer.write(_record())
        assert path.is_file()
        assert path.name.startswith("runs_")
        assert path.suffix == ".jsonl"

    def test_record_is_valid_json(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        path = writer.write(_record())
        line = path.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["run_id"] == "abc123"

    def test_multiple_writes_append(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        writer.write(_record(run_id="a"))
        writer.write(_record(run_id="b"))
        path = writer.today_path()
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2

    def test_timestamp_added_automatically(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        path = writer.write({"run_id": "x", "success": True})
        data = json.loads(path.read_text(encoding="utf-8").strip())
        assert "timestamp" in data


# ── DatasetWriter.write_golden() ─────────────────────────────────────────────


class TestDatasetWriterGolden:
    def test_golden_file_created(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        writer.write_golden(_record())
        assert (tmp_path / "golden_samples.jsonl").is_file()

    def test_golden_flag_injected(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        writer.write_golden(_record())
        line = (tmp_path / "golden_samples.jsonl").read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["_golden"] is True

    def test_original_record_not_mutated(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        rec = _record()
        writer.write_golden(rec)
        assert "_golden" not in rec  # shallow copy — original unchanged

    def test_count_golden_zero_when_no_file(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        assert writer.count_golden() == 0

    def test_count_golden_increments(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        writer.write_golden(_record(run_id="a"))
        writer.write_golden(_record(run_id="b"))
        assert writer.count_golden() == 2

    def test_golden_path_returns_correct_filename(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        assert writer.golden_path().name == "golden_samples.jsonl"


# ── DatasetWriter.export_finetune() ──────────────────────────────────────────


class TestDatasetWriterExportFinetune:
    def _write_runs(self, tmp_path, records):
        """Write records to a fake runs file and return writer."""
        writer = DatasetWriter(log_dir=tmp_path)
        runs_file = tmp_path / "runs_2026-01-01.jsonl"
        with runs_file.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return writer, [runs_file]

    def test_exports_successful_records(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [
            _record(run_id="a", success=True),
            _record(run_id="b", success=True),
        ])
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=src)
        assert count == 2
        assert out.is_file()

    def test_skips_failed_records(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [
            _record(run_id="a", success=True),
            _record(run_id="b", success=False),
        ])
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=src)
        assert count == 1

    def test_output_format_has_three_turns(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [_record(run_id="a")])
        out = tmp_path / "ft.jsonl"
        writer.export_finetune(out, source_files=src)
        sample = json.loads(out.read_text(encoding="utf-8").strip())
        assert "messages" in sample
        roles = [m["role"] for m in sample["messages"]]
        assert roles == ["system", "user", "assistant"]

    def test_user_turn_contains_prompt(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [_record(run_id="a", prompt="a bracket")])
        out = tmp_path / "ft.jsonl"
        writer.export_finetune(out, source_files=src)
        sample = json.loads(out.read_text(encoding="utf-8").strip())
        user_msg = next(m for m in sample["messages"] if m["role"] == "user")
        assert "bracket" in user_msg["content"]

    def test_assistant_turn_contains_code_fence(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [_record(run_id="a")])
        out = tmp_path / "ft.jsonl"
        writer.export_finetune(out, source_files=src)
        sample = json.loads(out.read_text(encoding="utf-8").strip())
        asst = next(m for m in sample["messages"] if m["role"] == "assistant")
        assert "```python" in asst["content"]
        assert "build_model" in asst["content"]

    def test_golden_only_flag(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [
            _record(run_id="a", success=True, golden=True),
            _record(run_id="b", success=True, golden=False),
        ])
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=src, golden_only=True)
        assert count == 1

    def test_deduplication_by_run_id(self, tmp_path):
        # Same run_id in two different source files should be deduplicated
        rec = _record(run_id="dup")
        f1 = tmp_path / "runs_2026-01-01.jsonl"
        f2 = tmp_path / "runs_2026-01-02.jsonl"
        f1.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        f2.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        writer = DatasetWriter(log_dir=tmp_path)
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=[f1, f2])
        assert count == 1

    def test_skips_records_without_code(self, tmp_path):
        rec = {"run_id": "x", "success": True, "prompt": "a box", "generated_code": ""}
        writer, src = self._write_runs(tmp_path, [rec])
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=src)
        assert count == 0

    def test_skips_records_without_prompt(self, tmp_path):
        rec = {"run_id": "x", "success": True, "prompt": "", "generated_code": "def build_model(): pass"}
        writer, src = self._write_runs(tmp_path, [rec])
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=src)
        assert count == 0

    def test_empty_source_files_writes_empty_output(self, tmp_path):
        writer = DatasetWriter(log_dir=tmp_path)
        out = tmp_path / "ft.jsonl"
        count = writer.export_finetune(out, source_files=[])
        assert count == 0
        assert out.is_file()

    def test_custom_system_prompt_used(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [_record(run_id="a")])
        out = tmp_path / "ft.jsonl"
        writer.export_finetune(out, source_files=src, system_prompt="My custom system")
        sample = json.loads(out.read_text(encoding="utf-8").strip())
        sys_msg = next(m for m in sample["messages"] if m["role"] == "system")
        assert sys_msg["content"] == "My custom system"

    def test_output_dir_created_automatically(self, tmp_path):
        writer, src = self._write_runs(tmp_path, [_record(run_id="a")])
        out = tmp_path / "nested" / "deep" / "ft.jsonl"
        writer.export_finetune(out, source_files=src)
        assert out.is_file()


# ── _load_records helper ──────────────────────────────────────────────────────


class TestLoadRecords:
    def test_loads_valid_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2}) + "\n",
            encoding="utf-8",
        )
        records = _load_records([f])
        assert len(records) == 2

    def test_skips_empty_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("\n" + json.dumps({"a": 1}) + "\n\n", encoding="utf-8")
        records = _load_records([f])
        assert len(records) == 1

    def test_skips_bad_json_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("not json\n" + json.dumps({"a": 1}) + "\n", encoding="utf-8")
        records = _load_records([f])
        assert len(records) == 1

    def test_missing_file_silently_skipped(self, tmp_path):
        records = _load_records([tmp_path / "nonexistent.jsonl"])
        assert records == []

    def test_multiple_files_merged(self, tmp_path):
        f1 = tmp_path / "a.jsonl"
        f2 = tmp_path / "b.jsonl"
        f1.write_text(json.dumps({"id": 1}) + "\n", encoding="utf-8")
        f2.write_text(json.dumps({"id": 2}) + "\n", encoding="utf-8")
        records = _load_records([f1, f2])
        assert len(records) == 2
