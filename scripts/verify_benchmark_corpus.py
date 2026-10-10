"""Correctness-only MB gate for the fixed corpus and additional canaries.

No compiler/runtime timings are published. Performance sampling is authorized
by all_required_targets_passed only after real images satisfy their contracts.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_suite import load_manifest
from scripts.verify_mb_reference import DEFAULT_SOURCE, build_reference_gate, verify_image


def digest_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def source_hashes(snapshot):
    return {str(path.relative_to(snapshot)): digest_file(path)
            for folder in ('malbolge', 'scripts', 'benchmarks')
            for path in sorted((snapshot / folder).rglob('*'))
            if path.is_file() and path.suffix in ('.py', '.json')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--canaries', required=True, type=Path)
    parser.add_argument('--compile-timeout', type=float, default=600)
    parser.add_argument('--gate-timeout', type=float)
    parser.add_argument('--cohort', default='working-latest')
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--workloads', nargs='+')
    parser.add_argument('--backends', nargs='+', choices=('c', 'direct', 'ir'),
                        default=('c', 'direct', 'ir'))
    parser.add_argument('--skip-canaries', action='store_true')
    parser.add_argument('--skip-corpus', action='store_true')
    parser.add_argument('--canary-cases', nargs='+')
    parser.add_argument('--max-steps', type=int,
                        help='explicit verification-only step budget override')
    args = parser.parse_args()
    snapshot, output = args.snapshot.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    _, programs = load_manifest(snapshot / 'benchmarks/manifest.json')
    canaries = json.loads(args.canaries.read_text())['canaries']
    if args.max_steps is not None and args.max_steps < 0:
        raise ValueError('max steps must be nonnegative')
    if args.cases:
        known = {program['id'] for program in programs}
        if set(args.cases) - known:
            raise ValueError('unknown corpus case')
        programs = [program for program in programs if program['id'] in args.cases]
    if args.workloads:
        known = {work['id'] for program in programs for work in program['workloads']}
        if set(args.workloads) - known:
            raise ValueError('unknown workload')
        programs = [dict(program, workloads=[work for work in program['workloads']
                                            if work['id'] in args.workloads])
                    for program in programs]
        programs = [program for program in programs if program['workloads']]
    if args.skip_canaries:
        canaries = []
    if args.skip_corpus:
        programs = []
    if args.canary_cases:
        known = {canary['name'] for canary in canaries}
        if set(args.canary_cases) - known:
            raise ValueError('unknown canary')
        canaries = [canary for canary in canaries if canary['name'] in args.canary_cases]
    cases = []
    for program in programs:
        workloads = [dict(work, stdin_hex=work['stdin'].encode('ascii').hex(),
                          expected_stdout_hex=work['stdout'].encode('ascii').hex(),
                          expected_input_consumed=len(work['stdin'].encode('ascii')))
                     for work in program['workloads']]
        cases.append({'id': program['id'], 'kind': 'corpus',
                      'source': program['source'], 'workloads': workloads})
    for canary in canaries:
        cases.append({'id': canary['name'], 'kind': 'canary',
                      'source': canary['source'], 'workloads': [dict(canary,
                          id='fixed', max_steps=1000000000, timeout_seconds=300)]})
    binary, reference_manifest = build_reference_gate(DEFAULT_SOURCE, output / 'reference-gate')
    report = {'schema_version': 1, 'phase': 'correctness_only', 'cohort': args.cohort,
              'snapshot': str(snapshot),
              'required_corpus_targets': sum(len(program['workloads']) for program in programs) * len(args.backends),
              'required_canary_targets': len(canaries) * len(args.backends),
              'selection': {'target_pipeline': 'structured', 'style': 'cluster/main',
                            'backends': list(args.backends), 'ir_frontend': 'semantic'},
              'verification_only_budget_override': args.max_steps,
              'policy': 'Exact stdout/input consumption/normal HALT before performance. '
                        'Budget or timeout is unvalidated, not success. '
                        'Reference counters are correctness data, not speed metrics.',
              'source_hashes_start': source_hashes(snapshot),
              'reference_gate': reference_manifest, 'state': 'running',
              'active': None, 'samples': []}

    def save():
        results = [work for sample in report['samples'] for work in sample['workloads']]
        report['attempted_targets'] = len(results)
        report['passed_targets'] = sum(work.get('gate_pass', False) for work in results)
        report['failed_or_unvalidated_targets'] = len(results) - report['passed_targets']
        temporary = output / 'report.json.tmp'
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(output / 'report.json')

    save()
    for case in cases:
        for backend in args.backends:
            folder = output / (case['kind'] + '-' + case['id'] + '-' + backend)
            folder.mkdir()
            source, image = folder / 'source.py', folder / 'program.mb'
            source.write_text(case['source'])
            sample = {'program': case['id'], 'kind': case['kind'], 'backend': backend,
                      'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                      'workloads': []}
            report['samples'].append(sample)
            command = [sys.executable, '-m', 'malbolge', 'compile', str(source),
                       '--backend', backend, '--target-pipeline', 'structured',
                       '--op-style', 'cluster', '--jmp-style', 'main', '-o', str(image)]
            if backend == 'ir':
                command.extend(('--ir-frontend', 'semantic'))
            report['active'] = {'task': 'compile_for_correctness', 'program': case['id'],
                                'backend': backend, 'timeout_seconds': args.compile_timeout}
            save()
            try:
                process = subprocess.run(command, cwd=snapshot, capture_output=True,
                                         timeout=args.compile_timeout)
                compile_ok = process.returncode == 0 and image.exists()
                sample['compilation'] = {'accepted': compile_ok, 'returncode': process.returncode,
                                         'stderr': process.stderr.decode(errors='replace')[-6000:]}
            except subprocess.TimeoutExpired:
                compile_ok = False
                sample['compilation'] = {'accepted': False, 'reason': 'compile_timeout'}
            if compile_ok:
                sample['image'] = {'bytes': image.stat().st_size, 'sha256': digest_file(image)}
            for work in case['workloads']:
                report['active'] = {'task': 'reference_correctness', 'program': case['id'],
                                    'backend': backend, 'workload': work['id']}
                save()
                if compile_ok:
                    result = verify_image(binary, image, bytes.fromhex(work['stdin_hex']),
                        bytes.fromhex(work['expected_stdout_hex']), work['expected_input_consumed'],
                        args.max_steps if args.max_steps is not None else work['max_steps'], 4096,
                        args.gate_timeout or work['timeout_seconds'])
                else:
                    result = {'gate_pass': False, 'validation_status': 'not_run',
                              'reason': 'compilation_not_accepted'}
                result.update(workload=work['id'], stdin_hex=work['stdin_hex'],
                              expected_stdout_hex=work['expected_stdout_hex'],
                              expected_input_consumed=work['expected_input_consumed'],
                              manifest_max_steps=work['max_steps'],
                              verification_max_steps=(args.max_steps if args.max_steps is not None else work['max_steps']))
                sample['workloads'].append(result)
                (folder / ('gate-' + work['id'] + '.json')).write_text(json.dumps(result, indent=2) + '\n')
                save()
            if image.exists():
                image.unlink()
            report['active'] = None
            save()
            print(json.dumps({'phase': 'correctness', 'program': case['id'], 'backend': backend,
                  'passed': sum(work.get('gate_pass', False) for work in sample['workloads']),
                  'requested': len(sample['workloads']), 'total_passed': report['passed_targets'],
                  'total_attempted': report['attempted_targets']}), flush=True)
    report['source_hashes_end'] = source_hashes(snapshot)
    report['source_unchanged'] = report['source_hashes_start'] == report['source_hashes_end']
    report['all_required_targets_passed'] = (report['source_unchanged'] and
        report['attempted_targets'] == report['required_corpus_targets'] + report['required_canary_targets'] and
        report['failed_or_unvalidated_targets'] == 0)
    report['state'] = 'passed' if report['all_required_targets_passed'] else 'needs_diagnosis'
    save()
    print(json.dumps({'state': report['state'], 'passed': report['passed_targets'],
                      'attempted': report['attempted_targets'], 'report': str(output / 'report.json')}), flush=True)
    return 0 if report['all_required_targets_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
