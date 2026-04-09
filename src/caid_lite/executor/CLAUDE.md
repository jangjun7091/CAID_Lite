# executor/ — Subprocess Sandbox

## Purpose
Run untrusted LLM-generated CadQuery code in an isolated child process with a hard timeout.
The parent process is protected from crashes, segfaults, and infinite loops.

## Files
- `sandbox.py` — `Sandbox`: spawns the runner, parses result, returns `ExecutionResult`
- `runner_template.py` — copied to a temp dir and executed as a subprocess entry point
- `result.py` — `ExecutionResult` dataclass (plain data; no subprocess logic)
- `runner_import.py` — subprocess for importing user-supplied STEP/STL files

## Interface contract
```python
class Sandbox:
    def execute(self, code: str, run_id: str) -> ExecutionResult: ...

@dataclass
class ExecutionResult:
    run_id: str; success: bool; stdout: str; stderr: str
    exception: Optional[str]; exports: Dict[str, Path]
    elapsed_s: float; timed_out: bool = False
```
- `Sandbox` is duck-typed — `MockSandbox` satisfies the interface without inheritance.
- `execute()` always returns an `ExecutionResult`; it never raises.
- `exports` keys are format names (`"step"`, `"stl"`); values are absolute `Path` objects.

## Runner contract (runner_template.py)
The runner enforces the `build_model()` contract before importing CadQuery:
1. `exec` user code into a namespace.
2. Check `callable(namespace["build_model"])` — fail fast if missing or non-callable.
3. Call `build_model()` — catch all exceptions.
4. Check `isinstance(result, cq.Workplane)` — fail with type name if wrong.
5. Export each format via `cq.exporters.export()`; catch per-format errors.
6. Print a single JSON line to stdout; always exit 0.

## runner_import.py contract
Called by `SessionManager._run_import()` via `asyncio.to_thread`.
```
python runner_import.py <out_dir> <run_id> <source_path>
```
- STEP (`.step`/`.stp`): `cq.importers.importStep()` → validate → export STEP + STL
- STL (`.stl`): `shutil.copy` to output dir only (no re-export)
- JSON stdout: `{"success": bool, "step_path": str|null, "stl_path": str|null,
                 "validation_metrics": {...}, "error": str|null}`
- Always exits 0; errors reported via `success=False`.

## Architecture rules
- `Sandbox` must not import `cadquery` — only the runner subprocess does.
- `shell=False` on all `subprocess.run` calls — no command injection.
- `TimeoutExpired` → `timed_out=True`; empty/non-JSON stdout → `success=False`.
- Output files land in `output_dir / run_id /`; the runner creates this directory.
- `Sandbox.from_config(cfg)` reads `executor.timeout_s`, `exporter.output_dir`,
  `exporter.formats` from the parsed YAML dict.

## Dependency constraints
- `sandbox.py`, `result.py`: stdlib only (`subprocess`, `tempfile`, `shutil`, `json`, `pathlib`).
- `runner_template.py`: `cadquery` — imported only inside the subprocess.
- No imports from `llm`, `validator`, `repair`, `session`, or `api`.
