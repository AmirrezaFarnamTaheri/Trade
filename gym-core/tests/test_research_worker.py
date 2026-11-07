"""Run: PYTHONPATH=gym-core/src python -m unittest discover -s gym-core/tests -p test_research_worker.py"""
import ctypes
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gym.services import research_worker as worker


class Function:
    def __init__(self, result):
        self.result = result

    def __call__(self, *args):
        return self.result(*args) if callable(self.result) else self.result


class ResearchWorkerTests(unittest.TestCase):
    def test_actual_server_has_only_r0_tools_and_rejects_code(self):
        source = io.StringIO('\n'.join(json.dumps(request) for request in (
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "exec", "arguments": {"code": "print(1)"}}},
        )) + '\n')
        sink = io.StringIO()
        worker.serve_stdio(Path.cwd(), source, sink)
        listed, rejected = map(json.loads, sink.getvalue().splitlines())
        self.assertEqual({tool['name'] for tool in listed['result']['tools']}, {'strategy_catalog', 'research_state', 'market_coverage'})
        self.assertTrue(rejected['result']['isError'])

    def test_installed_entrypoint_delegates_to_existing_server(self):
        with patch.object(worker.sys, 'argv', ['research_worker', str(Path.cwd())]), patch.object(worker, 'serve_stdio', return_value=7) as serve:
            self.assertEqual(worker.main(), 7)
            serve.assert_called_once_with(Path.cwd())
        with patch.object(worker.sys, 'argv', ['research_worker', 'relative']):
            with self.assertRaises(SystemExit):
                worker.main()

    def test_probe_mode_still_runs_real_r0_server(self):
        with patch.object(worker.sys, 'argv', ['research_worker', str(Path.cwd()), '--boundary-probe']), patch.object(worker, 'boundary_probe', return_value=3) as probe, patch.object(worker, 'serve_stdio', return_value=0) as serve:
            self.assertEqual(worker.main(), 3)
            probe.assert_called_once_with(Path.cwd())
            serve.assert_called_once_with(Path.cwd())

    def probe(self, error, opened=False, accessible_access=None, accessible_target=None):
        kernel = type('Kernel', (), {})()
        kernel.CreateFileW = Function(lambda path, access, *rest: 42 if opened or access == accessible_access or path == accessible_target else ctypes.c_void_p(-1).value)
        kernel.CloseHandle = Function(1)
        advapi = type('Advapi', (), {})()
        advapi.OpenSCManagerW = Function(21)
        advapi.OpenServiceW = Function(42 if opened else 0)
        advapi.CloseServiceHandle = Function(1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'inputs'
            targets = {name: name for name in ('stop_pipe', 'operate_pipe', 't2_pipe', 'vault', 'core_journal', 'profile_canary', 'service')}
            (root.parent / 'boundary.json').write_text(json.dumps(targets), encoding='utf-8')
            output = io.StringIO()
            with patch.object(ctypes, 'WinDLL', side_effect=[kernel, advapi], create=True), patch.object(ctypes, 'get_last_error', return_value=error, create=True), redirect_stdout(output):
                code = worker.boundary_probe(root)
            return code, json.loads(output.getvalue())

    def test_missing_or_busy_targets_never_pass(self):
        for error in (2, 3, 231, 1060):
            code, report = self.probe(error)
            self.assertEqual(code, 3)
            self.assertTrue(all(value.startswith('NOT_VERIFIED') for value in report['results'].values()))

    def test_denial_and_unexpected_open_are_distinct(self):
        code, report = self.probe(5)
        self.assertEqual(code, 0)
        self.assertEqual(set(report['results'].values()), {'DENIED'})
        code, report = self.probe(0, opened=True)
        self.assertEqual(code, 3)
        self.assertEqual(set(report['results'].values()), {'FAIL_OPENED'})
        code, report = self.probe(5, accessible_access=1)
        self.assertEqual(code, 3)
        self.assertEqual(report['results']['service'], 'DENIED')
        for name in ('stop_pipe', 'operate_pipe', 't2_pipe', 'vault', 'core_journal', 'profile_canary'):
            self.assertEqual(report['results'][name], 'FAIL_OPENED')

    def test_partial_data_grants_and_actual_ipc_access_cannot_pass(self):
        for access in (0x1, 0x2, 0x4, 0xC0000000):
            with self.subTest(access=access):
                code, report = self.probe(5, accessible_access=access)
                self.assertEqual(code, 3)
                for name in ('stop_pipe', 'operate_pipe', 't2_pipe', 'vault', 'core_journal', 'profile_canary'):
                    self.assertEqual(report['results'][name], 'FAIL_OPENED')

    def test_operator_profile_access_cannot_be_hidden_by_denied_money_resources(self):
        code, report = self.probe(5, accessible_target='profile_canary')
        self.assertEqual(code, 3)
        self.assertEqual(report['results']['profile_canary'], 'FAIL_OPENED')
        for name in ('stop_pipe', 'operate_pipe', 't2_pipe', 'vault', 'core_journal', 'service'):
            self.assertEqual(report['results'][name], 'DENIED')


if __name__ == '__main__':
    unittest.main()
