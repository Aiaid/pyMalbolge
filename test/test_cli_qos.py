"""Output-integrity, cache, streamed compiler and bounded-run CLI regressions."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from malbolge.compiler import cli
from malbolge.compiler.mc2mb import assemble_mc_to_mb, iter_mc_to_mb


def instructions(*opcodes):
    return ''.join(next(chr(c) for c in range(33, 127) if (c + i) % 94 == op)
                   for i, op in enumerate(opcodes))


class CompilerOutputSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.py'
        self.source.write_text('putchar(65)\n')

    def error(self, argv, text):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as err:
            cli.main(argv)
        self.assertEqual(err.exception.code, 1)
        self.assertIn(text, stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertEqual(self.source.read_text(), 'putchar(65)\n')

    def test_source_aliases_and_duplicate_outputs_rejected(self):
        self.error([str(self.source), '--emit-c', str(self.source)], 'overwrite')
        link = self.root / 'source-link.py'
        link.symlink_to(self.source)
        self.error([str(self.source), '--emit-c', str(link)], 'overwrite')
        hard = self.root / 'source-hard.py'
        os.link(self.source, hard)
        self.error([str(self.source), '--emit-c', str(hard)], 'overwrite')
        output = str(self.root / 'same.txt')
        self.error([str(self.source), '--emit-c', output, '--emit-mg', output], 'distinct')
        self.error([str(self.source), '--emit-c', '-', '--emit-mg', '-'], 'distinct')

    def test_bad_destination_preflight_and_encoding_diagnostics(self):
        self.error([str(self.source), '--emit-c', str(self.root/'missing'/'out.c')],
                   'directory does not exist')
        bad = self.root / 'bad.py'
        bad.write_bytes(b'\xff')
        self.error([str(bad), '--emit-c', str(self.root/'out.c')], 'file I/O failed')

    def test_atomic_failure_keeps_last_good_artifact(self):
        target = self.root / 'old.mb'
        target.write_bytes(b'last good artifact')
        def failing_chunks():
            yield b'partial replacement'
            raise OSError('simulated disk failure')
        with self.assertRaises(OSError):
            cli._atomic_write(target, failing_chunks())
        self.assertEqual(target.read_bytes(), b'last good artifact')
        self.assertEqual(list(self.root.glob('.old.mb.*')), [])

    def test_cache_hit_and_corruption_rebuild(self):
        cache, target = self.root/'cache', self.root/'out.mb'
        argv = [str(self.source), '--backend=direct', '-o', str(target),
                '--cache-dir', str(cache), '--stats']
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli.main(argv)
        initial = target.read_bytes()
        with patch.object(cli, 'compile_python_to_mg', side_effect=AssertionError('cache miss')):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                cli.main(argv)
        metrics = json.loads(stderr.getvalue().splitlines()[-1])
        self.assertTrue(metrics['stages'][0]['cache_hit'])
        self.assertGreaterEqual(metrics['stages'][0]['seconds'], 0)
        self.assertEqual(target.read_bytes(), initial)
        next(cache.glob('*/program.mb')).write_bytes(b'corrupt')
        with contextlib.redirect_stderr(io.StringIO()):
            cli.main(argv)
        self.assertEqual(target.read_bytes(), initial)
        # Source changes create a different cache namespace.
        self.source.write_text('putchar(66)\n')
        with contextlib.redirect_stderr(io.StringIO()):
            cli.main(argv)
        self.assertNotEqual(target.read_bytes(), initial)
        self.assertEqual(len(list(cache.glob('*/manifest.json'))), 2)

    def test_stream_matches_frozen_fixture_digest(self):
        source = Path('test/fixtures/nagoya/mg_a_minimal.mc').read_text()
        streamed = b''.join(iter_mc_to_mb(source, 997))
        self.assertEqual(streamed, assemble_mc_to_mb(source).encode('ascii'))
        self.assertEqual(hashlib.sha256(streamed).hexdigest(),
                         '9cd064c41ec8b699a3287f980197a78da7268464e1fec85ab4a0dceffa7aa4a0')
        with self.assertRaises(ValueError):
            list(iter_mc_to_mb(source, 0))

    def test_source_function_names_and_diagnostics_match_backends(self):
        from malbolge.compiler import compile_python_to_c, compile_python_to_mg
        for compiler in (compile_python_to_c, compile_python_to_mg):
            with self.subTest(compiler=compiler.__name__):
                with self.assertRaises((cli.CompileError, cli.Py2MgError)) as caught:
                    compiler('def foo():\n    return 65\nputchar(FOO())\n')
                self.assertEqual(caught.exception.lineno, 3)
                with self.assertRaises((cli.CompileError, cli.Py2MgError)) as caught:
                    compiler('def end():\n    return 65\nputchar(end())\n')
                self.assertEqual(caught.exception.lineno, 1)
                self.assertIn('reserved', str(caught.exception))
                self.assertTrue(compiler('def Foo():\n    return 65\nputchar(Foo())\n'))


class RuntimeCli(unittest.TestCase):
    def run_cli(self, source, *args, input=b''):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'program.mal'
            path.write_text(source)
            return subprocess.run([sys.executable, '-m', 'malbolge',
                                   '--variant=malbolge20', str(path), *args],
                                  input=input, capture_output=True, timeout=10)

    def test_limits_exit_codes_and_json_metrics(self):
        source = instructions(23, 5, 81)
        proc = self.run_cli(source, '--input', 'X', '--max-steps', '1', '--stats')
        self.assertEqual((proc.returncode, proc.stdout), (3, b''))
        stats = json.loads(proc.stderr)
        self.assertEqual((stats['steps'], stats['stop_reason'], stats['input_consumed']),
                         (1, 'step_limit', 1))
        self.assertNotIn('output_hex', stats)
        proc = self.run_cli(source, '--input', 'X', '--max-output', '1', '--stats')
        self.assertEqual((proc.returncode, proc.stdout), (0, b'X'))
        self.assertEqual(json.loads(proc.stderr)['stop_reason'], 'terminated')
        proc = self.run_cli(source, '--input', 'X', '--max-output', '0', '--stats')
        self.assertEqual((proc.returncode, proc.stdout), (3, b''))
        self.assertEqual(json.loads(proc.stderr)['stop_reason'], 'output_limit')

    def test_eof_utf8_and_binary_file_input(self):
        source = instructions(23, 5, 81)
        proc = self.run_cli(source, '--input', '', '--eof', 'stop', '--stats')
        self.assertEqual((proc.returncode, proc.stdout), (0, b''))
        self.assertEqual(json.loads(proc.stderr)['stop_reason'], 'input_exhausted')
        proc = self.run_cli(source, '--input', 'é', '--stats')
        self.assertEqual((proc.returncode, proc.stdout), (0, b'\xc3'))
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'stdin.bin'
            data.write_bytes(b'\xff')
            proc = self.run_cli(source, '--input-file', str(data), '--stats')
        self.assertEqual((proc.returncode, proc.stdout), (0, b'\xff'))

    def test_unknown_flags_are_not_silently_ignored(self):
        proc = self.run_cli(instructions(81), '--max-stepz', '1')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b'unrecognized', proc.stderr)
        self.assertNotIn(b'Traceback', proc.stderr)

    def test_legacy_file_encoding_errors_are_concise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invalid.mal'
            path.write_bytes(b'\xff')
            for variant in ('malbolge', 'malbolge20'):
                with self.subTest(variant=variant):
                    proc = subprocess.run(
                        [sys.executable, '-m', 'malbolge', '--variant', variant, str(path)],
                        capture_output=True, timeout=10)
                    self.assertEqual(proc.returncode, 1)
                    self.assertEqual(proc.stdout, b'')
                    self.assertIn(b'cannot read', proc.stderr)
                    self.assertNotIn(b'Traceback', proc.stderr)


if __name__ == '__main__':
    unittest.main()
