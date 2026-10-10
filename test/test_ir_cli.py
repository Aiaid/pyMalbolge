"""Optional IR CLI integration, atomic output and cache boundaries."""

import contextlib
from importlib import metadata
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from malbolge.compiler import cli, compile_python_to_mb
from malbolge.compiler.ir import IRDependencyError
from malbolge.compiler.mc2mb import parse_mc_to_data
from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.compiler.py2mg import compile_python_to_mg
from malbolge.malbolge20 import run


try:
    HAS_IR = sys.version_info >= (3, 10) and metadata.version('xdsl') == '0.69.0'
except metadata.PackageNotFoundError:
    HAS_IR = False


class IRConfigurationErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.py'
        self.source.write_text('putchar(65)\n')

    def error(self, arguments, expected):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            cli.main([str(self.source)] + arguments)
        self.assertEqual(error.exception.code, 1)
        self.assertIn(expected, stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertEqual(self.source.read_text(), 'putchar(65)\n')

    def test_ir_options_require_ir_backend(self):
        self.error(['--backend=c', '--emit-ir', '-'], 'require --backend=ir')
        self.error(['--backend=direct', '--passes', 'verify-lal'], 'only available')
        self.error(['--backend=ir', '--emit-c', '-'], 'requires --backend=c')

    def test_missing_optional_dependency_precedes_any_output(self):
        target = self.root / 'out.mlir'
        target.write_text('last good IR')
        with patch.object(cli, 'require_ir_support', side_effect=IRDependencyError('uv sync --extra ir')):
            self.error(['--backend=ir', '--emit-ir', str(target)], 'uv sync --extra ir')
        self.assertEqual(target.read_text(), 'last good IR')

    def test_pass_option_rejected_by_legacy_library_api(self):
        with self.assertRaisesRegex(ValueError, "only available"):
            compile_python_to_mb('putchar(65)', backend='direct', passes=['verify-lal'])


@unittest.skipUnless(HAS_IR, 'optional pinned xDSL IR environment required')
class IRCompilerCLI(IRConfigurationErrors):
    def invoke(self, arguments):
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            cli.main([str(self.source), '--backend=ir', '--ir-frontend=compat',
                      '--target-pipeline=text'] + arguments)
        return stdout.getvalue(), stderr.getvalue()

    def test_default_ir_output_is_inspectable(self):
        from malbolge.compiler.ir import parse_lal, verify_lal
        text, stderr = self.invoke([])
        self.assertIn('lal.', text)
        verify_lal(parse_lal(text))
        self.assertEqual(stderr, '')

    def test_multi_stage_outputs_and_real_vm_match_direct(self):
        from malbolge.compiler.ir import parse_lal, emit_mc
        paths = [self.root / name for name in ('out.mg', 'out.mc', 'out.mlir', 'out.mb')]
        mg, mc, ir, mb = paths
        _, stderr = self.invoke(['--emit-mg', str(mg), '--emit-mc', str(mc),
                                 '--emit-ir', str(ir), '-o', str(mb), '--stats'])
        self.assertEqual(mg.read_text(), compile_python_to_mg(self.source.read_text()))
        self.assertEqual(mc.read_text(), emit_mc(parse_lal(ir.read_text())))
        reference_mc = translate_mg_to_mc(mg.read_text())
        self.assertEqual(parse_mc_to_data(mc.read_text()), parse_mc_to_data(reference_mc))
        image = mb.read_text()
        self.assertEqual(image, compile_python_to_mb(self.source.read_text(), backend='direct'))
        result = run(image, max_steps=1_000_000, max_output=16)
        self.assertEqual(result.output, b'A')
        self.assertEqual(result.stop_reason, 'terminated')
        stats = json.loads(stderr.splitlines()[-1])
        self.assertEqual(stats['ir']['passes'], ['verify-lal'])
        self.assertEqual(stats['ir']['reports'][0]['before'], stats['ir']['reports'][0]['after'])
        self.assertIn('lal-to-mc', [stage['stage'] for stage in stats['stages']])

    def test_ir_output_aliases_are_rejected(self):
        self.error(['--backend=ir', '--emit-ir', str(self.source)], 'overwrite')
        target = str(self.root / 'same')
        self.error(['--backend=ir', '--emit-ir', target, '--emit-mc', target], 'distinct')
        self.error(['--backend=ir', '--emit-ir', '-', '--emit-mc', '-'], 'distinct')

    def test_unknown_pass_fails_before_compilation_and_output(self):
        target = self.root / 'out.mlir'
        target.write_text('last good IR')
        with patch.object(cli, 'compile_python_to_mg', side_effect=AssertionError('frontend ran')):
            self.error(['--backend=ir', '--passes', 'missing-pass', '--emit-ir', str(target)], 'Unknown IR pass')
        self.assertEqual(target.read_text(), 'last good IR')
        self.error(['--backend=ir', '--passes', ''], 'nonempty')

    def test_ir_parse_failure_keeps_previous_output(self):
        target = self.root / 'out.mlir'
        target.write_text('last good IR')
        with patch.object(cli, 'translate_mg_to_mc', return_value='unsupported MC'):
            self.error(['--backend=ir', '--ir-frontend=compat', '--target-pipeline=text',
                        '--emit-ir', str(target)], 'IR stage failed')
        self.assertEqual(target.read_text(), 'last good IR')

    def test_cache_pass_configuration_and_corruption(self):
        cache = self.root / 'cache'
        target = self.root / 'out.mlir'
        arguments = ['--emit-ir', str(target), '--cache-dir', str(cache), '--stats']
        self.invoke(arguments)
        initial = target.read_text()
        with patch.object(cli, 'compile_python_to_mg', side_effect=AssertionError('frontend ran')):
            _, stderr = self.invoke(arguments)
        stats = json.loads(stderr.splitlines()[-1])
        self.assertTrue(all(stage['cache_hit'] for stage in stats['stages']))
        self.assertEqual(stats['ir']['passes'], ['verify-lal'])
        self.assertTrue(stats['ir']['cache_hit'])
        self.assertEqual(stats['ir']['cached_stage'], 'ir')
        self.assertEqual(stats['ir']['reports'], [])
        self.assertIn('ir_digest', stats['ir']['summary'])
        self.assertEqual(target.read_text(), initial)
        next(cache.glob('*/program.ir')).write_text('corrupt')
        self.invoke(arguments)
        self.assertEqual(target.read_text(), initial)
        self.invoke(arguments + ['--passes', 'verify-lal,verify-lal'])
        self.assertEqual(len(list(cache.glob('*/manifest.json'))), 2)
        self.assertEqual(target.read_text(), initial)

    def test_complete_image_cache_reports_selection_without_replaying_passes(self):
        cache, target = self.root / 'cache', self.root / 'out.mb'
        arguments = ['-o', str(target), '--cache-dir', str(cache), '--stats']
        self.invoke(arguments)
        with patch.object(cli, 'compile_python_to_mg', side_effect=AssertionError('frontend ran')):
            _, stderr = self.invoke(arguments)
        stats = json.loads(stderr.splitlines()[-1])
        self.assertEqual(stats['ir']['passes'], ['verify-lal'])
        self.assertEqual(stats['ir']['cached_stage'], 'mb')
        self.assertEqual(stats['ir']['reports'], [])


if __name__ == '__main__':
    unittest.main()
