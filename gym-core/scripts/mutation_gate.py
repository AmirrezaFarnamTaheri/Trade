"""Blocking, fingerprinted mutmut cohort; the broader weekly assessment is separate."""
import argparse
import ast
import difflib
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

SCOPE = {
    "src/gym/domain/sim.py": ["CashBook", "_floor"],
    "src/gym/contracts/stop_wire.py": ["verify_reply_for"],
    "src/gym/domain/performance.py": ["expected_max_sharpe"],
}
TESTS = ["tests/test_simulation.py", "tests/test_stop_wire_contract.py", "tests/test_honest_sharpe.py",
         "tests/test_mutation_contracts.py"]
RUNNER = "python -B -m pytest -x -q -p no:cacheprovider " + " ".join(TESTS)
TIMING = {"test_time_base": 2.0, "test_time_multiplier": 2.0}


def fingerprint(path, before, after):
    # Hunk offsets change after unrelated edits; the mutation and its context do not.
    diff = "".join(line for line in difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), n=3)
        if not line.startswith(("@@", "---", "+++")))
    return path + ":" + hashlib.sha256(diff.encode()).hexdigest(), diff


def check(expected, actual):
    if not expected or set(expected) != set(actual):
        raise ValueError("mutation cohort changed or is incomplete; review every added/removed fingerprint")
    for key, result in actual.items():
        if expected[key]["status"] not in {"killed", "equivalent"}:
            raise ValueError(f"invalid reviewed baseline status: {key}")
        if expected[key]["status"] == "equivalent" and not expected[key].get("reason"):
            raise ValueError(f"equivalent mutation requires a reviewed proof: {key}")
        if result not in {"killed", "survived"}:
            raise ValueError(f"incomplete/error mutation result: {key}: {result}")
        if result == "survived" and expected[key]["status"] != "equivalent":
            raise ValueError(f"new surviving mutation: {key}")


def run(root, output):
    # A reused directory may contain a green result from a different execution.
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": 1, "scope": SCOPE, "runner": RUNNER, "timing": TIMING,
              "runner_sha256": hashlib.sha256(RUNNER.encode()).hexdigest(),
              "python": sys.version, "platform": sys.platform, "stage": "preflight", "mutants": {}}
    with tempfile.TemporaryDirectory(prefix="trade-mutation-gate-") as directory:
        isolated = Path(directory) / "gym-core"
        try:
            return evaluate(root, output, isolated, report)
        except Exception as error:
            report["failure"] = {"type": type(error).__name__, "message": str(error)}
            if isinstance(error, subprocess.CalledProcessError):
                report["failure"].update(stdout=error.stdout, stderr=error.stderr)
            raise
        finally:
            preservation_error = None
            try:
                for suffix in ("", "-wal", "-shm", "-journal"):
                    cache = isolated / (".mutmut-cache" + suffix)
                    if cache.is_file():
                        shutil.copy2(cache, output / ("mutmut-cache.sqlite" + suffix))
            except OSError as error:
                preservation_error = error
                report["evidence_failure"] = str(error)
            report["outcome"] = "FAILED" if "failure" in report else "COMPLETE"
            if preservation_error:
                report["outcome"] = "FAILED"
            (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            if preservation_error:
                raise preservation_error


def evaluate(root, output, isolated, report):
    from importlib.metadata import version

    from mutmut import Context, list_mutations, mutate

    if version("mutmut") != "2.5.1":
        raise ValueError("mutmut 2.5.1 is required")
    report.update(mutmut=version("mutmut"), patch_parser=version("whatthepatch"),
                  tool_sha256={name: hashlib.sha256((Path(sys.modules["mutmut"].__file__).parent / name).read_bytes()).hexdigest()
                               for name in ("__init__.py", "__main__.py", "cache.py")})
    report["stage"] = "isolation"
    for name in ("src", "tests"):
        shutil.copytree(root / name, isolated / name, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copytree(root.parent / "contracts", isolated.parent / "contracts")
    source_hashes = {path: hashlib.sha256((isolated / path).read_text(encoding="utf-8").encode()).hexdigest() for path in SCOPE}
    test_hashes = {path: hashlib.sha256((isolated / path).read_text(encoding="utf-8").encode()).hexdigest() for path in TESTS}
    report.update(source_sha256=source_hashes, test_sha256=test_hashes, stage="generation")
    expected, identities, patch = {}, {}, []
    report["mutants"] = expected
    for path, symbols in SCOPE.items():
        source = (isolated / path).read_text(encoding="utf-8")
        nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        lines = set()
        patch.extend([f"diff --git {path} {path}\n", f"--- {path}\n", f"+++ {path}\n"])
        for symbol in symbols:
            node = nodes[symbol]
            lines.update(range(node.lineno, node.end_lineno + 1))
            selected = source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno]
            patch.append(f"@@ -{node.lineno},0 +{node.lineno},{len(selected)} @@\n")
            patch.extend("+" + line for line in selected)
        for mutation in list_mutations(Context(source=source, filename=path)):
            if mutation.line_number + 1 not in lines:
                continue
            changed, count = mutate(Context(source=source, filename=path, mutation_id=mutation))
            if count != 1:
                raise ValueError("mutmut did not apply exactly one mutation")
            key, diff = fingerprint(path, source, changed)
            if key in expected:
                raise ValueError("duplicate mutation fingerprint")
            expected[key] = {"diff": diff}
            identities[(path, mutation.line_number, mutation.index)] = key
    (isolated / "cohort.patch").write_text("".join(patch), encoding="utf-8")
    (output / "cohort.patch").write_text("".join(patch), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(isolated / "src"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    report["stage"] = "import_probe"
    # The isolated import path is checked before the baseline and every mutation run.
    probe = subprocess.run([sys.executable, "-c", "import gym.domain.sim; print(gym.domain.sim.__file__)"],
                           cwd=isolated, env=env, text=True, capture_output=True, check=True)
    if Path(probe.stdout.strip()).resolve() != (isolated / "src/gym/domain/sim.py").resolve():
        raise ValueError("mutation imports escaped the isolated copy")
    command = [sys.executable, "-m", "mutmut", "run", "--paths-to-mutate", ",".join(str(Path(path)) for path in SCOPE),
               "--use-patch-file", "cohort.patch", "--tests-dir", "tests", "--runner", RUNNER,
               "--test-time-base", str(TIMING["test_time_base"]),
               "--test-time-multiplier", str(TIMING["test_time_multiplier"]),
               "--simple-output", "--no-progress"]
    report.update(stage="mutmut", command=command)
    with (
        (output / "mutmut.log").open("w", encoding="utf-8") as log,
        subprocess.Popen(command, cwd=isolated, env=env, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=os.name != "nt") as process,
    ):
        try:
            returncode = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True,
                               capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    report.update(returncode=returncode, stage="cache_validation")
    if not (isolated / ".mutmut-cache").is_file():
        raise ValueError(f"mutmut produced no cache: exit {returncode}")
    with closing(sqlite3.connect(isolated / ".mutmut-cache")) as connection:
        rows = connection.execute("SELECT SourceFile.filename, Line.line_number, Mutant.[index], Mutant.status "
                                  "FROM Mutant JOIN Line ON Mutant.line=Line.id "
                                  "JOIN SourceFile ON Line.sourcefile=SourceFile.id").fetchall()
    report["cache_rows"] = rows
    actual = {}
    for path, line, index, status in rows:
        identity = (path.replace("\\", "/"), line, index)
        if identity not in identities:
            raise ValueError(f"unexpected cached mutant: {identity}")
        key = identities[identity]
        if key in actual:
            raise ValueError("duplicate cached mutant")
        actual[key] = {"ok_killed": "killed", "bad_survived": "survived"}.get(status, status)
        expected[key]["status"] = actual[key]
    if set(actual) != set(expected):
        raise ValueError("mutmut cache did not evaluate the exact expected cohort")
    if source_hashes != {path: hashlib.sha256((isolated / path).read_text(encoding="utf-8").encode()).hexdigest() for path in SCOPE}:
        raise ValueError("mutmut did not restore the isolated source")
    if returncode not in (0, 2):
        raise ValueError(f"mutmut tool/baseline/timeout failure: exit {returncode}")
    report["stage"] = "evaluated"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = arguments.output.resolve()
    try:
        baseline = json.loads((root / "mutation-baseline.json").read_text(encoding="utf-8"))
        if baseline.get("qualification") != "COMPLETE":
            raise ValueError(f"mutation baseline is pending qualification: {baseline.get('reason', 'no complete evidence')}")
    except Exception as error:
        output.mkdir(parents=True, exist_ok=False)
        (output / "results.json").write_text(json.dumps({"outcome": "FAILED", "stage": "baseline",
            "scope": SCOPE, "runner": RUNNER, "timing": TIMING,
            "failure": {"type": type(error).__name__, "message": str(error)}}, indent=2) + "\n", encoding="utf-8")
        raise
    report = run(root, output)
    try:
        if any(baseline[key] != report[key] for key in (
                "schema", "mutmut", "tool_sha256", "patch_parser", "scope", "runner", "runner_sha256", "timing")):
            raise ValueError("mutation configuration differs from reviewed baseline")
        check(baseline["mutants"], {key: value["status"] for key, value in report["mutants"].items()})
    except Exception as error:
        report.update(outcome="FAILED", stage="baseline_comparison",
                      failure={"type": type(error).__name__, "message": str(error)})
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise
    print(f"Mutation gate passed: {len(report['mutants'])} complete fingerprinted mutants")


if __name__ == "__main__":
    main()
