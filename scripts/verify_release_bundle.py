#!/usr/bin/env python3
"""Create or verify an offline exact-source review bundle. Never uploads."""
import argparse
import base64
import csv
import io
import hashlib
import json
import re
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

LICENSES = {'LICENSE', 'THIRD_PARTY_NOTICES.md'} | {
    'licenses/' + name + '.txt' for name in (
        'nagoya-highlevel', 'nagoya-lowass', 'nagoya-malbolge20-interpreter', 'nagoya-ternary')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_portable(path, version):
    if path.name.endswith('.whl'):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if not n.endswith('/')]
            require(len(names) == len(set(names)), 'duplicate wheel member')
            files = {n: archive.read(n) for n in names}
        require(path.name == 'malbolge-' + version + '-py3-none-any.whl', 'pure wheel filename mismatch')
        dist = 'malbolge-' + version + '.dist-info/'
        wheel = BytesParser().parsebytes(files[dist + 'WHEEL'])
        require(wheel.get_all('Root-Is-Purelib') == ['true'], 'pure wheel Root-Is-Purelib mismatch')
        require(wheel.get_all('Tag') == ['py3-none-any'], 'pure wheel tag mismatch')
        record_name = dist + 'RECORD'
        rows = list(csv.reader(io.StringIO(files[record_name].decode('utf8'))))
        require(all(len(row) == 3 for row in rows), 'invalid pure RECORD row')
        require(len({row[0] for row in rows}) == len(rows), 'duplicate pure RECORD row')
        require({row[0] for row in rows} == set(files), 'pure RECORD file coverage mismatch')
        for name, recorded_hash, size in rows:
            if name == record_name:
                require(recorded_hash == size == '', 'pure RECORD self hash must be empty')
                continue
            digest_bytes = hashlib.sha256(files[name]).digest()
            encoded = base64.urlsafe_b64encode(digest_bytes).decode().rstrip('=')
            require(recorded_hash == 'sha256=' + encoded and size == str(len(files[name])),
                    'pure RECORD hash/size mismatch: ' + name)
        metadata_name = 'malbolge-' + version + '.dist-info/METADATA'
        license_prefix = 'malbolge-' + version + '.dist-info/licenses/'
        require(not any(n.endswith(('.so', '.pyd', '.dll', '.dylib')) for n in files), 'native binary in pure wheel')
    else:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            require(all(m.isfile() or m.isdir() for m in members), 'links or special files in sdist')
            names = [m.name for m in members if m.isfile()]
            require(len(names) == len(set(names)), 'duplicate sdist member')
            files = {m.name: archive.extractfile(m).read() for m in members if m.isfile()}
        prefix = 'malbolge-' + version + '/'
        require(all(n.startswith(prefix) for n in files), 'sdist root mismatch')
        files = {n[len(prefix):]: data for n, data in files.items()}
        metadata_name, license_prefix = 'PKG-INFO', ''
    for name in files:
        parts = PurePosixPath(name).parts
        require(not name.startswith('/') and '..' not in parts, 'unsafe archive path')
        require(not set(parts) & {'.git', '.venv', '.claude', '__pycache__'}, 'private/cache content')
        require(not any(p in name for p in ('docs/research/', 'test/fixtures/hell/', 'test/test_hell_examples.py')),
                'excluded research content')
    metadata = BytesParser().parsebytes(files[metadata_name])
    require(metadata['Name'] == 'malbolge' and metadata['Version'] == version, 'archive version/name mismatch')
    require(set(metadata.get_all('License-File', [])) == LICENSES, 'license metadata mismatch')
    for name in LICENSES:
        require(bool(files.get(license_prefix + name, b'').strip()), 'missing license: ' + name)
    require(re.search(r'^__version__\s*=\s*[\'\"]' + re.escape(version) + r'[\'\"]',
                      files['malbolge/__init__.py'].decode('utf8'), re.M), 'module version mismatch')
    return {name[len('malbolge/'):]: hashlib.sha256(data).hexdigest()
            for name, data in files.items() if name.startswith('malbolge/') and name.endswith('.py')}


def collect_bundle(root, version, commit, run_id, attempt):
    report = json.loads((root / 'native-report.json').read_text(encoding='utf8'))
    require(report.get('status') == 'passed' and report.get('mode') == 'full'
            and report.get('complete_release_matrix') is True and report.get('wheel_count') == 35,
            'bundle requires a successful full native matrix')
    identity = {'version': version, 'source_commit': commit,
                'workflow_run': str(run_id), 'workflow_attempt': str(attempt)}
    for key, value in identity.items():
        require(report.get(key) == value, 'native report identity mismatch: ' + key)
    expected = {}
    for entry in report['artifacts']:
        name = Path(entry['path']).name
        require(name not in expected and name.endswith('.whl') and '-cp38-' not in name,
                'duplicate or non-publishable wheel')
        expected[name] = entry
    require(len(expected) == 35, 'native report must list 35 wheels')
    pure = 'malbolge-' + version + '-py3-none-any.whl'
    sdist = 'malbolge-' + version + '.tar.gz'
    paths = sorted((root / 'dist').iterdir())
    require({p.name for p in paths} == set(expected) | {pure, sdist}, 'missing or extra distribution files')
    artifacts = []
    module_hashes = {}
    for path in paths:
        require(path.is_file() and not path.is_symlink(), 'distribution must be a regular file')
        entry = {'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
        if path.name in expected:
            for key in ('bytes', 'sha256'):
                require(entry[key] == expected[path.name][key], 'native artifact mismatch: ' + path.name)
        else:
            module_hashes['pure' if path.name == pure else 'sdist'] = inspect_portable(path, version)
        artifacts.append(entry)
    acceptance = {}
    for mode in ('pure', 'sdist'):
        path = root / (mode + '-acceptance.json')
        data = json.loads(path.read_text(encoding='utf8'))
        require(data.get('success') is True, 'portable acceptance failed')
        for key, value in identity.items():
            require(str(data.get(key)) == value, 'portable acceptance identity mismatch: ' + key)
        hashes = data.get('module_sha256', {})
        require(isinstance(hashes, dict), 'invalid accepted module hashes')
        normalized = {name.replace('\\', '/'): value for name, value in hashes.items()}
        require(len(normalized) == len(hashes), 'duplicate normalized accepted module path')
        if mode == 'pure':
            require(normalized == module_hashes[mode], 'pure accepted module hashes mismatch')
            require(data.get('native_available') is False, 'pure acceptance unexpectedly exposes native VM')
        else:
            sources = {name: value for name, value in normalized.items() if name.endswith('.py')}
            require(sources == module_hashes[mode], 'sdist accepted module hashes mismatch')
            extensions = {name for name in normalized if not name.endswith('.py')}
            require(extensions and all(name.startswith('_native_vm') and name.endswith(('.so', '.pyd'))
                                       and '/' not in name for name in extensions),
                    'sdist acceptance requires only the generated native VM extension')
            require(data.get('native_available') is True, 'sdist native acceptance missing')
        acceptance[path.name] = digest(path)
    return dict(identity, schema_version=1, complete_release_matrix=True, artifacts=artifacts,
                native_report_sha256=digest(root / 'native-report.json'), acceptance_sha256=acceptance)


def verify_bundle(root, version, commit, run_id, attempt):
    expected = collect_bundle(root, version, commit, run_id, attempt)
    actual = json.loads((root / 'release-manifest.json').read_text(encoding='utf8'))
    require(actual == expected, 'bundle manifest mismatch')
    return actual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dir', type=Path, required=True)
    parser.add_argument('--create', action='store_true')
    for key in ('version', 'commit', 'run-id', 'attempt'):
        parser.add_argument('--expected-' + key, required=True)
    args = parser.parse_args(argv)
    values = (args.bundle_dir, args.expected_version, args.expected_commit, args.expected_run_id, args.expected_attempt)
    if args.create:
        (args.bundle_dir / 'release-manifest.json').write_text(json.dumps(collect_bundle(*values), indent=2, sort_keys=True) + '\n')
    verify_bundle(*values)
    print('Verified 37 exact-source review artifacts; no publication performed.')


if __name__ == '__main__':
    main()
