"""Synthetic offline acceptance tests for the native release artifact gate."""
import base64
import csv
import importlib.util
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('release_artifacts', Path(__file__).parents[1] / 'scripts/verify_release_artifacts.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
VERSION = '1.2.0'
COMMIT = 'a' * 40


def macho(arch='arm64', minimum=(11, 0, 0), legacy=False):
    value = minimum[0] << 16 | minimum[1] << 8 | minimum[2]
    command = struct.pack('<4I', 0x24, 16, value, value) if legacy else struct.pack('<6I', 0x32, 24, 1, value, value, 0)
    return struct.pack('<8I', 0xfeedfacf, 0x100000c if arch == 'arm64' else 0x1000007,
                       0, 8, 1, len(command), 0, 0) + command


def make_wheel(directory, identifier, edit=None):
    python, family = identifier.split('-', 1)
    platform = {'manylinux_x86_64': 'manylinux_2_17_x86_64.manylinux2014_x86_64',
                'manylinux_aarch64': 'manylinux_2_17_aarch64.manylinux2014_aarch64',
                'musllinux_x86_64': 'musllinux_1_2_x86_64', 'musllinux_aarch64': 'musllinux_1_2_aarch64',
                'macosx_arm64': 'macosx_11_0_arm64', 'macosx_x86_64': 'macosx_11_0_x86_64',
                'win_amd64': 'win_amd64'}[family]
    dist = 'malbolge-' + VERSION + '.dist-info/'
    extension = 'malbolge/_native_vm.' + python + ('.pyd' if family == 'win_amd64' else '.so')
    binary = macho(family[7:]) if family.startswith('macosx') else b'native fixture'
    files = {'malbolge/__init__.py': b'__version__ = "1.2.0"\n', extension: binary,
             dist + 'METADATA': ('Name: malbolge\nVersion: ' + VERSION + '\n' + ''.join(
                 'License-File: ' + name + '\n' for name in sorted(gate.LICENSES))).encode(),
             dist + 'WHEEL': ('Wheel-Version: 1.0\nRoot-Is-Purelib: false\n' + ''.join(
                 'Tag: {}-{}-{}\n'.format(python, python, p) for p in platform.split('.'))).encode()}
    for name in gate.LICENSES:
        files[dist + 'licenses/' + name] = b'MIT notice fixture\n'
    if edit:
        edit(files, dist, extension)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\n')
    for name, data in files.items():
        writer.writerow((name, 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(gate.sha256(data))).rstrip(b'=').decode(), str(len(data))))
    writer.writerow((dist + 'RECORD', '', ''))
    files[dist + 'RECORD'] = output.getvalue().encode()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('malbolge-{}-{}-{}-{}.whl'.format(VERSION, python, python, platform))
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('malbolge/', b'')  # Explicit ZIP directories need no RECORD row.
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def fixture(directory, mode='smoke'):
    manifests = {}
    for identifier in sorted(gate.expected_identifiers(mode)):
        runner = identifier.split('-', 1)[1]
        path = make_wheel(directory / ('native-wheels-' + runner), identifier)
        wheel = gate.validate_wheel(path, VERSION)
        provenance = directory / ('native-provenance-' + runner)
        provenance.mkdir(exist_ok=True)
        common = {'version': VERSION, 'source_commit': COMMIT, 'workflow_run': '123',
                  'workflow_attempt': '2', 'build_identifier': identifier}
        native = dict(common, status='passed', modules={'malbolge._native_vm': {'sha256': wheel['extension_sha256']}},
                      wheel_metadata=wheel['wheel_metadata'])
        release = dict(common, success=True, module_sha256=wheel['module_sha256'])
        for prefix, report in (('', native), ('release-', release)):
            (provenance / (prefix + identifier + '.json')).write_text(json.dumps(report))
        manifests.setdefault(runner, []).append({k: wheel[k] for k in ('file', 'bytes', 'sha256', 'wheel_metadata')})
    for runner, wheels in manifests.items():
        (directory / ('native-provenance-' + runner) / 'artifacts.json').write_text(json.dumps({'commit': COMMIT, 'wheels': wheels}))


def validate(directory, mode='smoke'):
    return gate.validate_artifacts(directory, VERSION, COMMIT, '123', '2', mode)


@pytest.mark.parametrize('mode,count', [('full', 35), ('smoke', 7), ('macos-arm64-only', 5)])
def test_valid_matrix(tmp_path, mode, count):
    fixture(tmp_path, mode)
    report = validate(tmp_path, mode)
    assert report['wheel_count'] == count
    assert report['complete_release_matrix'] == (mode == 'full')
    assert report['partial_retry'] == (mode == 'macos-arm64-only')
    assert report['macos_floors']


def test_missing_wheel(tmp_path):
    fixture(tmp_path)
    next(tmp_path.rglob('*.whl')).unlink()
    with pytest.raises(ValueError, match='missing identifiers'):
        validate(tmp_path)


def test_extra_compatibility_wheel(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'cp38-compat.whl').write_bytes(b'compatibility')
    with pytest.raises(ValueError, match='outside native publication'):
        validate(tmp_path)


@pytest.mark.parametrize('field,value', [('version', '0.1'), ('source_commit', 'wrong'), ('workflow_run', '1'),
                                        ('workflow_attempt', '1'), ('build_identifier', 'cp38-linux_x86_64'),
                                        ('status', 'failed'), ('modules', {})])
def test_bad_native_report(tmp_path, field, value):
    fixture(tmp_path)
    path = next(tmp_path.glob('native-provenance-*/cp312-*.json'))
    report = json.loads(path.read_text())
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        validate(tmp_path)


@pytest.mark.parametrize('change', ['missing', 'failed', 'hash', 'extra'])
def test_bad_release_report(tmp_path, change):
    fixture(tmp_path)
    path = next(tmp_path.glob('native-provenance-*/release-*.json'))
    if change == 'missing':
        path.unlink()
    elif change == 'extra':
        path.with_name('unexpected.json').write_text('{}')
    else:
        report = json.loads(path.read_text())
        report['success' if change == 'failed' else 'module_sha256'] = False if change == 'failed' else {}
        path.write_text(json.dumps(report))
    with pytest.raises((ValueError, OSError)):
        validate(tmp_path)


@pytest.mark.parametrize('field,value', [('commit', 'wrong'), ('sha256', 'wrong'), ('bytes', 0)])
def test_manifest_mismatch(tmp_path, field, value):
    fixture(tmp_path)
    path = next(tmp_path.glob('native-provenance-*/artifacts.json'))
    data = json.loads(path.read_text())
    if field == 'commit':
        data[field] = value
    else:
        data['wheels'][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='mismatch'):
        validate(tmp_path)


@pytest.mark.parametrize('change', ['version', 'tag', 'notice', 'license_metadata', 'private', 'binary', 'cache', 'architecture', 'floor'])
def test_invalid_wheel(tmp_path, change):
    def edit(files, dist, extension):
        if change == 'version':
            files[dist + 'METADATA'] = files[dist + 'METADATA'].replace(b'1.2.0', b'0.1.0')
        elif change == 'tag':
            files[dist + 'WHEEL'] = files[dist + 'WHEEL'].replace(b'cp312', b'cp311')
        elif change == 'notice':
            del files[dist + 'licenses/LICENSE']
        elif change == 'license_metadata':
            files[dist + 'METADATA'] = b'Name: malbolge\nVersion: 1.2.0\n'
        elif change in ('private', 'cache', 'binary'):
            files[{'private': 'malbolge/research/secret.txt', 'cache': 'malbolge/__pycache__/x.pyc',
                   'binary': 'malbolge/extra.dll'}[change]] = b'bad'
        elif change == 'architecture':
            files[extension] = macho('x86_64')
        else:
            files[extension] = macho(minimum=(12, 0, 0))
    path = make_wheel(tmp_path, 'cp312-macosx_arm64', edit)
    with pytest.raises(ValueError):
        gate.validate_wheel(path, VERSION)


@pytest.mark.parametrize('change', ['hash', 'coverage', 'duplicate'])
def test_record_tamper(tmp_path, change):
    path = make_wheel(tmp_path, 'cp312-win_amd64')
    with zipfile.ZipFile(path) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    record = 'malbolge-1.2.0.dist-info/RECORD'
    if change == 'hash':
        files['malbolge/__init__.py'] = b'tamper'
    elif change == 'coverage':
        files['malbolge/new.py'] = b'extra'
    else:
        files[record] += files[record].splitlines(keepends=True)[0]
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match='RECORD'):
        gate.validate_wheel(path, VERSION)


def test_legacy_macho_and_truncation():
    assert gate.macho_floor(macho('x86_64', (10, 13, 0), True), 'x86_64') == (10, 13, 0)
    for data in (b'', b'not a Mach-O' * 10, macho()[:-1]):
        with pytest.raises(ValueError):
            gate.macho_floor(data, 'arm64')


def test_cli_writes_failure_report(tmp_path):
    report = tmp_path / 'out' / 'report.json'
    assert gate.main(['--artifacts-dir', str(tmp_path), '--expected-version', VERSION,
                      '--expected-commit', COMMIT, '--expected-run-id', '123', '--expected-attempt', '2',
                      '--mode', 'full', '--report', str(report)]) == 1
    assert json.loads(report.read_text())['status'] == 'failed'
