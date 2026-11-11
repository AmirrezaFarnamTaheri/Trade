"""The mutation ratchet fails closed on missing evidence and new coverage debt."""
import importlib.util
import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("mutation_gate", Path(__file__).parents[1] / "scripts/mutation_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_complete_killed_cohort_passes_and_equivalent_mutation_can_be_killed():
    gate.check({"one": {"status": "killed"}, "two": {"status": "equivalent", "reason": "Reviewed proof"}},
               {"one": "killed", "two": "killed"})


@pytest.mark.parametrize("actual", [{}, {"new": "killed"}, {"one": "survived"},
                                    {"one": "untested"}, {"one": "timeout"},
                                    {"one": "suspicious"}, {"one": "tool-error"}])
def test_missing_new_or_failed_mutation_evidence_fails(actual):
    with pytest.raises(ValueError):
        gate.check({"one": {"status": "killed"}}, actual)


def test_equivalent_survivor_without_explicit_proof_cannot_be_waived():
    with pytest.raises(ValueError, match="reviewed proof"):
        gate.check({"one": {"status": "equivalent"}}, {"one": "survived"})


def test_pending_baseline_fails_before_launching_mutations(tmp_path, monkeypatch):
    (tmp_path / "mutation-baseline.json").write_text(json.dumps({"qualification": "PENDING", "reason": "timing evidence"}))
    monkeypatch.setattr(gate, "__file__", str(tmp_path / "scripts/mutation_gate.py"))
    monkeypatch.setattr(gate.sys, "argv", ["mutation_gate.py", "--output", str(tmp_path / "output")])
    monkeypatch.setattr(gate, "run", lambda *_: pytest.fail("pending evidence must not launch mutations"))
    with pytest.raises(ValueError, match="pending qualification: timing evidence"):
        gate.main()
    report = json.loads((tmp_path / "output/results.json").read_text())
    assert report["stage"] == "baseline" and report["outcome"] == "FAILED"
    assert not (tmp_path / "output/mutmut-cache.sqlite").exists()


def test_reused_evidence_directory_is_rejected_without_overwriting_it(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    old = output / "results.json"
    old.write_text("previous execution")
    with pytest.raises(FileExistsError):
        gate.run(tmp_path, output)
    assert old.read_text() == "previous execution"


@pytest.mark.parametrize("failure", ["timeout", "import", "cardinality", "preflight"])
def test_failed_execution_preserves_evidence_before_temporary_cleanup(tmp_path, monkeypatch, failure):
    import importlib.metadata

    root = tmp_path / "project/gym-core"
    source = root / "src/gym/domain/sim.py"
    source.parent.mkdir(parents=True)
    source.write_text("def money():\n    return 1\n")
    (root / "tests").mkdir()
    (root.parent / "contracts").mkdir()
    tool = tmp_path / "tool"
    tool.mkdir()
    for name in ("__init__.py", "__main__.py", "cache.py"):
        (tool / name).write_text("# pinned fake mutation tool\n")
    module = SimpleNamespace(__file__=str(tool / "__init__.py"),
        Context=lambda **kwargs: kwargs,
        list_mutations=lambda _: [SimpleNamespace(line_number=1, index=0)],
        mutate=lambda context: (context["source"].replace("return 1", "return 2"), 1))
    monkeypatch.setitem(gate.sys.modules, "mutmut", module)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "wrong" if failure == "preflight" else (
        "2.5.1" if name == "mutmut" else "0.0.6"))
    monkeypatch.setattr(gate, "SCOPE", {"src/gym/domain/sim.py": ["money"]})
    monkeypatch.setattr(gate, "TESTS", [])
    killed = []
    isolated_paths = []

    def probe(command, **kwargs):
        if command[0] == "taskkill":
            killed.append(command)
            return SimpleNamespace(returncode=0)
        if failure == "import":
            raise subprocess.CalledProcessError(1, command, output="probe output", stderr="probe failure")
        return SimpleNamespace(stdout=str(kwargs["cwd"] / "src/gym/domain/sim.py"))

    class Process:
        pid = 123456

        def __init__(self, command, **kwargs):
            isolated_paths.append(kwargs["cwd"])
            with closing(sqlite3.connect(kwargs["cwd"] / ".mutmut-cache")) as connection:
                connection.executescript("CREATE TABLE SourceFile(id INTEGER, filename TEXT);"
                    "CREATE TABLE Line(id INTEGER, sourcefile INTEGER, line_number INTEGER);"
                    "CREATE TABLE Mutant(line INTEGER, [index] INTEGER, status TEXT);")
            self.waits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def wait(self, timeout=None):
            self.waits += 1
            if failure == "timeout" and self.waits == 1:
                raise subprocess.TimeoutExpired("mutmut", timeout)
            return 0

    monkeypatch.setattr(gate.subprocess, "run", probe)
    monkeypatch.setattr(gate.subprocess, "Popen", Process)
    monkeypatch.setattr(gate.os, "killpg", lambda *args: killed.append(args), raising=False)
    output = tmp_path / "evidence"
    with pytest.raises((ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError)):
        gate.run(root, output)
    report = json.loads((output / "results.json").read_text())
    assert report["outcome"] == "FAILED" and report["failure"]["message"]
    assert report["scope"] and report["runner"] and report["timing"]
    if failure in {"timeout", "cardinality"}:
        assert (output / "mutmut-cache.sqlite").is_file()
        assert (output / "cohort.patch").is_file()
        assert next(iter(report["mutants"].values()))["diff"]
        assert report["source_sha256"] and report["tool_sha256"]
        assert not isolated_paths[0].exists()
    if failure == "timeout":
        assert killed and report["stage"] == "mutmut"
    if failure == "cardinality":
        assert report["cache_rows"] == [] and report["stage"] == "cache_validation"
    if failure == "import":
        assert report["failure"]["stderr"] == "probe failure"


def test_fingerprint_ignores_unrelated_line_offsets_but_keeps_path_and_mutation():
    first = gate.fingerprint("money.py", "a = 1\n", "a = 2\n")[0]
    shifted = gate.fingerprint("money.py", "\n" * 20 + "a = 1\n", "\n" * 20 + "a = 2\n")[0]
    # Leading context itself changes when fewer than three lines preceded a mutation.
    assert first != shifted
    before = "\n" * 4 + "a = 1\n"
    after = "\n" * 4 + "a = 2\n"
    assert gate.fingerprint("money.py", before, after)[0] == gate.fingerprint("money.py", "\n" * 20 + before, "\n" * 20 + after)[0]
    assert gate.fingerprint("codec.py", before, after)[0] != gate.fingerprint("money.py", before, after)[0]
