"""Offline bundle integrity checks; no package-index credentials or uploads."""
import importlib.util
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('release_bundle', Path(__file__).parents[1] / 'scripts/verify_release_bundle.py')
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dist = self.root / 'dist'
        self.dist.mkdir()
        self.identity = dict(version='1.2.0', source_commit='a' * 40, workflow_run='123', workflow_attempt='1')
        self.args = (self.root, '1.2.0', 'a' * 40, '123', '1')
        artifacts = []
        for i in range(35):
            path = self.dist / ('native-%02d.whl' % i)
            path.write_bytes(('native fixture %d' % i).encode())
            artifacts.append(dict(path='native-wheels-fixture/' + path.name,
                                  bytes=path.stat().st_size, sha256=bundle.digest(path)))
        report = dict(self.identity, status='passed', mode='full', complete_release_matrix=True,
                      wheel_count=35, artifacts=artifacts)
        self.write_json('native-report.json', report)
        for mode in ('pure', 'sdist'):
            self.write_json(mode + '-acceptance.json', dict(self.identity, success=True))
        metadata = ('Name: malbolge\nVersion: 1.2.0\n' + ''.join('License-File: ' + n + '\n' for n in sorted(bundle.LICENSES))).encode()
        files = {n: b'license notice' for n in bundle.LICENSES}
        files['malbolge/__init__.py'] = b'__version__ = "1.2.0"\n'
        with zipfile.ZipFile(self.dist / 'malbolge-1.2.0-py3-none-any.whl', 'w') as archive:
            archive.writestr('malbolge-1.2.0.dist-info/METADATA', metadata)
            for name, data in files.items():
                archive.writestr(('malbolge-1.2.0.dist-info/licenses/' if name in bundle.LICENSES else '') + name, data)
        with tarfile.open(self.dist / 'malbolge-1.2.0.tar.gz', 'w:gz') as archive:
            for name, data in dict(files, **{'PKG-INFO': metadata}).items():
                entry = tarfile.TarInfo('malbolge-1.2.0/' + name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        self.rewrite_wheel({'malbolge-1.2.0.dist-info/WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}, repair_record=True)
        hashes = {'__init__.py': hashlib.sha256(files['malbolge/__init__.py']).hexdigest()}
        for mode in ('pure', 'sdist'):
            accepted = dict(hashes)
            if mode == 'sdist':
                accepted['_native_vm.cpython-312-x86_64-linux-gnu.so'] = 'a' * 64
            self.write_json(mode + '-acceptance.json', dict(self.identity, success=True,
                            module_sha256=accepted, native_available=(mode == 'sdist')))
        self.write_json('release-manifest.json', bundle.collect_bundle(*self.args))

    def rewrite_wheel(self, changes, repair_record=False, directory=False):
        path = self.dist / 'malbolge-1.2.0-py3-none-any.whl'
        with zipfile.ZipFile(path) as archive:
            files = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        files.update(changes)
        if repair_record:
            record = 'malbolge-1.2.0.dist-info/RECORD'
            output = io.StringIO()
            writer = csv.writer(output, lineterminator='\n')
            for name, data in sorted(files.items()):
                if name != record:
                    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
                    writer.writerow((name, 'sha256=' + encoded, str(len(data))))
            writer.writerow((record, '', ''))
            files[record] = output.getvalue().encode()
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            if directory:
                archive.writestr('malbolge/', b'')

    def write_json(self, name, data):
        (self.root / name).write_text(json.dumps(data))

    def test_valid_bundle(self):
        self.assertEqual(len(bundle.verify_bundle(*self.args)['artifacts']), 37)

    def test_tampered_native(self):
        (self.dist / 'native-00.whl').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'artifact mismatch'):
            bundle.verify_bundle(*self.args)

    def test_missing_file(self):
        (self.dist / 'native-00.whl').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or extra'):
            bundle.verify_bundle(*self.args)

    def test_extra_cp38(self):
        (self.dist / 'malbolge-1.2.0-cp38-cp38-linux_x86_64.whl').write_bytes(b'compat')
        with self.assertRaisesRegex(ValueError, 'missing or extra'):
            bundle.verify_bundle(*self.args)

    def test_wrong_identity(self):
        for index, value in ((1, '1.2.1'), (2, 'b' * 40), (3, '124'), (4, '2')):
            args = list(self.args)
            args[index] = value
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'identity mismatch'):
                bundle.verify_bundle(*args)

    def test_manifest_tamper(self):
        self.write_json('release-manifest.json', {})
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            bundle.verify_bundle(*self.args)

    def test_partial_matrix_rejected(self):
        report = json.loads((self.root / 'native-report.json').read_text())
        report['mode'] = 'macos-arm64-only'
        self.write_json('native-report.json', report)
        with self.assertRaisesRegex(ValueError, 'full native matrix'):
            bundle.verify_bundle(*self.args)

    def test_failed_portable_acceptance(self):
        self.write_json('pure-acceptance.json', dict(self.identity, success=False))
        with self.assertRaisesRegex(ValueError, 'acceptance failed'):
            bundle.verify_bundle(*self.args)

    def test_notice_required(self):
        self.rewrite_wheel({'malbolge-1.2.0.dist-info/METADATA': b'Name: malbolge\nVersion: 1.2.0\n'}, repair_record=True)
        with self.assertRaisesRegex(ValueError, 'license metadata'):
            bundle.verify_bundle(*self.args)

    def test_record_hash_tamper(self):
        self.rewrite_wheel({'malbolge/__init__.py': b'__version__ = "1.2.0"\n# tampered\n'})
        with self.assertRaisesRegex(ValueError, 'RECORD hash/size'):
            bundle.collect_bundle(*self.args)

    def test_wheel_tag_and_purity(self):
        for data, error in ((b'Root-Is-Purelib: false\nTag: py3-none-any\n', 'Purelib'),
                            (b'Root-Is-Purelib: true\nTag: cp312-none-any\n', 'tag mismatch')):
            self.rewrite_wheel({'malbolge-1.2.0.dist-info/WHEEL': data}, repair_record=True)
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, error):
                bundle.collect_bundle(*self.args)

    def test_zip_directory_ignored(self):
        self.rewrite_wheel({}, directory=True)
        self.assertEqual(len(bundle.collect_bundle(*self.args)['artifacts']), 37)

    def test_accepted_source_mismatch(self):
        for mode in ('pure', 'sdist'):
            path = self.root / (mode + '-acceptance.json')
            original = json.loads(path.read_text())
            changed = json.loads(path.read_text())
            changed['module_sha256']['__init__.py'] = '0' * 64
            self.write_json(path.name, changed)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, mode + ' accepted module hashes mismatch'):
                bundle.collect_bundle(*self.args)
            self.write_json(path.name, original)

    def test_missing_or_extra_accepted_sources(self):
        path = self.root / 'pure-acceptance.json'
        original = json.loads(path.read_text())
        for hashes in ({}, dict(original['module_sha256'], extra_py='0' * 64)):
            self.write_json(path.name, dict(original, module_sha256=hashes))
            with self.subTest(hashes=hashes), self.assertRaisesRegex(ValueError, 'accepted module hashes mismatch'):
                bundle.collect_bundle(*self.args)

    def test_portable_acceptance_identity(self):
        path = self.root / 'sdist-acceptance.json'
        original = json.loads(path.read_text())
        for key in ('source_commit', 'workflow_run', 'workflow_attempt'):
            self.write_json(path.name, dict(original, **{key: 'wrong'}))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'acceptance identity mismatch'):
                bundle.collect_bundle(*self.args)

    def test_consistent_record_still_requires_accepted_source(self):
        self.rewrite_wheel({'malbolge/__init__.py': b'__version__ = "1.2.0"\n# changed\n'}, repair_record=True)
        with self.assertRaisesRegex(ValueError, 'pure accepted module hashes mismatch'):
            bundle.collect_bundle(*self.args)


if __name__ == '__main__':
    unittest.main()
