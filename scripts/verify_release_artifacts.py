#!/usr/bin/env python3
"""Offline, fail-closed gate for downloaded native wheel CI artifacts.

This verifies integrity and consistency, not cryptographic authenticity of CI
reports. Download artifacts only from the trusted expected workflow run.
"""
import argparse
import base64
import csv
import hashlib
import io
import itertools
import json
import re
import struct
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

LICENSES = {'LICENSE', 'THIRD_PARTY_NOTICES.md'} | {
    'licenses/' + name + '.txt' for name in (
        'nagoya-highlevel', 'nagoya-lowass', 'nagoya-malbolge20-interpreter', 'nagoya-ternary')}
PLATFORMS = ('manylinux_x86_64', 'manylinux_aarch64', 'musllinux_x86_64',
             'musllinux_aarch64', 'macosx_arm64', 'macosx_x86_64', 'win_amd64')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def expected_identifiers(mode):
    pythons = ('cp312',) if mode == 'smoke' else ('cp39', 'cp310', 'cp311', 'cp312', 'cp313')
    platforms = ('macosx_arm64',) if mode == 'macos-arm64-only' else PLATFORMS
    return {python + '-' + platform for python in pythons for platform in platforms}


def platform_family(tag):
    if tag == 'win_amd64':
        return tag
    match = re.fullmatch(r'(manylinux)(?:\d+|_\d+_\d+)_(x86_64|aarch64)', tag)
    if not match:
        match = re.fullmatch(r'(musllinux|macosx)_\d+_\d+_(x86_64|aarch64|arm64)', tag)
    require(match is not None, 'unsupported platform tag: ' + tag)
    return match[1] + '_' + match[2]


def macho_floor(data, architecture):
    require(len(data) >= 32, 'truncated Mach-O header')
    endian = {b'\xcf\xfa\xed\xfe': '<', b'\xfe\xed\xfa\xcf': '>'}.get(data[:4])
    require(endian is not None, 'extension must be thin 64-bit Mach-O')
    header = struct.unpack_from(endian + '8I', data)
    require(header[1] == {'arm64': 0x100000c, 'x86_64': 0x1000007}[architecture],
            'Mach-O architecture does not match wheel tag')
    end = 32 + header[5]
    require(end <= len(data), 'truncated Mach-O load commands')
    offset, floors = 32, []
    for _ in range(header[4]):
        require(offset + 8 <= end, 'truncated Mach-O command')
        command, size = struct.unpack_from(endian + '2I', data, offset)
        require(size >= 8 and offset + size <= end, 'invalid Mach-O command size')
        if command == 0x32:
            require(size >= 24, 'truncated LC_BUILD_VERSION')
            platform, minimum = struct.unpack_from(endian + '2I', data, offset + 8)
            require(platform == 1, 'Mach-O platform is not macOS')
            floors.append(minimum)
        elif command == 0x24:
            require(size >= 16, 'truncated LC_VERSION_MIN_MACOSX')
            floors.append(struct.unpack_from(endian + 'I', data, offset + 8)[0])
        offset += size
    require(offset == end and floors, 'missing or malformed Mach-O deployment target')
    value = max(floors)
    return (value >> 16, (value >> 8) & 255, value & 255)


def validate_wheel(path, version):
    """Validate a native wheel without importing/extracting any of its contents."""
    parts = path.name[:-4].split('-')
    require(path.suffix == '.whl' and len(parts) == 5, 'invalid wheel filename: ' + path.name)
    name, wheel_version, python, abi, platforms = parts
    require(name == 'malbolge' and wheel_version == version, 'wheel filename version/name mismatch')
    require(python in ('cp39', 'cp310', 'cp311', 'cp312', 'cp313') and abi == python,
            'unsupported Python/ABI tag (cp38 compatibility is not publishable)')
    platform_tags = platforms.split('.')
    families = {platform_family(tag) for tag in platform_tags}
    require(len(families) == 1, 'wheel spans inconsistent platform families')
    identifier = python + '-' + next(iter(families))
    dist = 'malbolge-' + version + '.dist-info/'
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'duplicate ZIP member')
        for info in archive.infolist():
            member = info.filename
            pure = PurePosixPath(member)
            require(not pure.is_absolute() and '..' not in pure.parts and '\\' not in member,
                    'unsafe archive path: ' + member)
            require((info.external_attr >> 16) & 0o170000 != 0o120000, 'symlink in wheel')
            require(member.startswith(('malbolge/', dist)), 'unexpected wheel path: ' + member)
            require(not any(part.startswith('.') or part in ('__pycache__', 'research', 'cache')
                            for part in pure.parts) and not member.endswith(('.pyc', '.pyo')),
                    'private research/cache in wheel: ' + member)
        files = {n: archive.read(n) for n in names if not n.endswith('/')}
        require(dist + 'METADATA' in files and dist + 'WHEEL' in files and dist + 'RECORD' in files,
                'missing wheel metadata')
        metadata = Parser().parsestr(files[dist + 'METADATA'].decode('utf8'))
        wheel_text = files[dist + 'WHEEL'].decode('utf8')
        wheel = Parser().parsestr(wheel_text)
        require(metadata.get_all('Name') == ['malbolge'] and metadata.get_all('Version') == [version],
                'METADATA version/name mismatch')
        require(wheel.get('Root-Is-Purelib') == 'false', 'native wheel marked pure')
        expected_tags = {'-'.join(tag) for tag in itertools.product(python.split('.'), abi.split('.'), platform_tags)}
        require(set(wheel.get_all('Tag', [])) == expected_tags, 'WHEEL tags disagree with filename')
        require(set(metadata.get_all('License-File', [])) == LICENSES, 'License-File metadata mismatch')
        for license_name in LICENSES:
            require(bool(files.get(dist + 'licenses/' + license_name, b'').strip()),
                    'missing/empty license notice: ' + license_name)
        rows = list(csv.reader(io.StringIO(files[dist + 'RECORD'].decode('utf8'))))
        require(all(len(row) == 3 for row in rows), 'malformed RECORD row')
        records = {row[0]: row[1:] for row in rows}
        require(len(records) == len(rows) and set(records) == set(files), 'RECORD coverage mismatch')
        for member, data in files.items():
            digest, size = records[member]
            if member == dist + 'RECORD':
                require(not digest and not size, 'RECORD self-entry must be unhashed')
                continue
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            require(digest == 'sha256=' + encoded and size == str(len(data)), 'RECORD mismatch: ' + member)
        binaries = [n for n in files if n.endswith(('.so', '.pyd', '.dll', '.dylib', '.exe', '.a', '.o'))
                    or files[n].startswith((b'\x7fELF', b'MZ', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'))]
        require(len(binaries) == 1 and re.fullmatch(r'malbolge/_native_vm[^/]*\.(so|pyd)', binaries[0]),
                'missing native VM or unexpected binaries')
        extension = binaries[0]
        require(extension.endswith('.pyd') == (families == {'win_amd64'}), 'native extension suffix mismatch')
        floors = None
        if next(iter(families)).startswith('macosx_'):
            architecture = next(iter(families))[7:]
            floor = macho_floor(files[extension], architecture)
            for tag in platform_tags:
                match = re.fullmatch(r'macosx_(\d+)_(\d+)_.+', tag)
                require((int(match[1]), int(match[2]), 0) >= floor,
                        'macOS wheel tag floor is below actual Mach-O minimum')
            floors = {'binary_minimum': '.'.join(map(str, floor)), 'wheel_tags': platform_tags}
        modules = {n[len('malbolge/'):]: sha256(data) for n, data in files.items()
                   if n.startswith('malbolge/') and n.endswith(('.py', '.so', '.pyd', '.dll', '.dylib'))}
        return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path.read_bytes()),
                'identifier': identifier, 'wheel_metadata': wheel_text, 'module_sha256': modules,
                'extension_sha256': sha256(files[extension]), 'macos_floor': floors}


def validate_artifacts(directory, version, commit, run_id, attempt, mode):
    expected = expected_identifiers(mode)
    manifest, seen = [], set()
    wheels = sorted(directory.rglob('*.whl'))
    require(wheels, 'no wheels found')
    manifests = {}
    used_reports = set()
    for path in wheels:
        relative = path.relative_to(directory)
        require(len(relative.parts) == 2 and relative.parts[0].startswith('native-wheels-'),
                'wheel outside native publication inputs (including cp38 compatibility): ' + str(relative))
        runner = relative.parts[0][len('native-wheels-'):]
        provenance = directory / ('native-provenance-' + runner)
        if runner not in manifests:
            data = json.loads((provenance / 'artifacts.json').read_text(encoding='utf8'))
            require(data.get('commit') == commit, 'artifact source commit mismatch')
            entries = data['wheels']
            require(len({e['file'] for e in entries}) == len(entries), 'duplicate artifact manifest wheel')
            manifests[runner] = {e['file']: e for e in entries}
        wheel = validate_wheel(path, version)
        identifier = wheel['identifier']
        require(identifier in expected and identifier not in seen, 'extra/duplicate wheel identifier: ' + identifier)
        seen.add(identifier)
        entry = manifests[runner].pop(path.name, None)
        require(entry is not None, 'wheel absent from build manifest')
        for key in ('sha256', 'bytes', 'wheel_metadata'):
            require(entry.get(key) == wheel[key], 'artifact manifest mismatch: ' + key)
        for prefix in ('', 'release-'):
            report_path = provenance / (prefix + identifier + '.json')
            report = json.loads(report_path.read_text(encoding='utf8'))
            used_reports.add(report_path)
            require(report.get('version') == version, 'installed report version mismatch')
            for key, value in (('source_commit', commit), ('workflow_run', run_id),
                               ('workflow_attempt', attempt), ('build_identifier', identifier)):
                require(str(report.get(key)) == str(value), 'installed report mismatch: ' + key)
            if prefix:
                require(report.get('success') is True, 'release installed smoke failed')
                normalized = {k.replace('\\', '/'): v for k, v in report.get('module_sha256', {}).items()}
                require(normalized == wheel['module_sha256'], 'release installed module hashes mismatch')
            else:
                require(report.get('status') == 'passed', 'native installed smoke failed')
                require(report.get('modules', {}).get('malbolge._native_vm', {}).get('sha256') == wheel['extension_sha256'],
                        'native installed extension hash mismatch')
                require(report.get('wheel_metadata') == wheel['wheel_metadata'], 'installed WHEEL metadata mismatch')
        wheel['path'] = relative.as_posix()
        manifest.append(wheel)
    require(seen == expected, 'missing identifiers: ' + ', '.join(sorted(expected - seen)))
    require(all(not entries for entries in manifests.values()), 'extra wheels in build manifest')
    all_reports = set(directory.glob('native-provenance-*/*.json'))
    require(all_reports == used_reports | {directory / ('native-provenance-' + runner) / 'artifacts.json'
                                          for runner in manifests}, 'extra/unmatched provenance report')
    return {'status': 'passed', 'mode': mode, 'complete_release_matrix': mode == 'full',
            'partial_retry': mode == 'macos-arm64-only', 'version': version, 'source_commit': commit,
            'workflow_run': str(run_id), 'workflow_attempt': str(attempt), 'wheel_count': len(manifest),
            'platform_coverage': sorted(seen), 'artifacts': manifest,
            'macos_floors': {w['identifier']: w['macos_floor'] for w in manifest if w['macos_floor']}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    for key in ('expected-version', 'expected-commit', 'expected-run-id', 'expected-attempt'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--mode', choices=('full', 'smoke', 'macos-arm64-only'), required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = validate_artifacts(args.artifacts_dir, args.expected_version, args.expected_commit,
                                    args.expected_run_id, args.expected_attempt, args.mode)
    except (ValueError, OSError, KeyError, TypeError, IndexError, UnicodeError, csv.Error,
            RuntimeError, struct.error, zipfile.BadZipFile) as error:
        report = {'status': 'failed', 'mode': args.mode, 'complete_release_matrix': False,
                  'error': '{}: {}'.format(type(error).__name__, error)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps({'status': report['status'], 'report': str(args.report)}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
