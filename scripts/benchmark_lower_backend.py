"""Compare frozen textual, current textual and native structured MG lowering.

Every compile and VM sample is a fresh child; imports, fingerprints and disk I/O
are excluded from stage clocks. Profiles are separate, explicitly instrumented
runs. Output includes failures/timeouts rather than treating them as runtimes.
"""
import argparse
import cProfile
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / 'test/fixtures/nagoya'
PATHS = ('baseline-text', 'current-text', 'structured')
STYLES = ('cluster/main', 'cluster/direct', 'inline/main', 'inline/direct')
DEFAULT_BASELINE = ROOT / 'docs/research/performance/2026-10-09-structured-lowering/baseline'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def cases():
    result = {}
    for name, filename, inp, out in (
        ('hello', 'mg_b_hi.mg', '', 'Hi'), ('echo', 'mg_c_echo.mg', 'Q', 'Q'),
        ('repeat', 'mg_d_repeat.mg', '', 'AAAA'), ('call', 'mg_e_call.mg', '', 'X')):
        result[name] = ((FIX / filename).read_text(), inp.encode(), out.encode())
    # Many initialized variables and operations stress layout/bootstrap; the
    # final ROT has a defined accumulator, independent of preceding operations.
    result['generated'] = ('\n'.join(
        ['VAR V%d = %d' % (i, 195 + i * 3) for i in range(24)] +
        ['DEF MAIN'] + ['  ROT V%d' % i for i in range(24)] +
        ['  OUTPUT', 'END', '']), b'', b'X')
    return result


def load_baseline(directory, name):
    file = directory / 'malbolge/compiler' / (name + '.py')
    spec = importlib.util.spec_from_file_location('frozen_' + name, str(file))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fingerprints(args):
    paths = list((ROOT / 'malbolge/compiler').rglob('*.py'))
    paths += [ROOT / 'malbolge/core.py', Path(__file__)]
    paths += list(Path(args.baseline).rglob('*.py'))
    result = {}
    for path in sorted(set(paths)):
        try:
            name = str(path.relative_to(ROOT))
        except ValueError:
            name = str(path)
        result[name] = digest(path.read_bytes())
    return result


def compile_worker(args):
    if args.path == 'baseline-text':
        mg2mc = load_baseline(Path(args.baseline), 'mg2mc')
        mc2mb = load_baseline(Path(args.baseline), 'mc2mb')
    else:
        from malbolge.compiler import mg2mc, mc2mb
    source, _, _ = cases()[args.case]
    op, jmp = args.style.split('/')
    stages = []

    def stage(name, fn):
        wall, cpu = time.perf_counter(), time.process_time()
        value = fn()
        stages.append({'stage': name, 'wall_seconds': time.perf_counter() - wall,
                       'cpu_seconds': time.process_time() - cpu})
        return value

    profile = cProfile.Profile() if args.profile else None
    if profile:
        profile.enable()
    wall, cpu = time.perf_counter(), time.process_time()
    if args.path == 'structured':
        lal = stage('mg_lowering', lambda: mg2mc.translate_mg_to_lal(
            source, op_style=op, jmp_style=jmp))
        image = stage('parse_layout', lambda: mc2mb.layout_lal_to_image(lal))
    else:
        mc = stage('mg_lowering', lambda: mg2mc.translate_mg_to_mc(
            source, op_style=op, jmp_style=jmp))
        data = stage('parse_layout', lambda: mc2mb.parse_mc_to_data(mc))
    asm = mc2mb._Assembler()
    stage('setup', asm.setup_data_module)
    if args.path == 'structured':
        stage('image_init_bootstrap', lambda: asm.memory_init_image(image))
    else:
        stage('image_init_bootstrap', lambda: asm.memory_init_code1(data))
    raw = stage('emission', lambda: b''.join(asm.iter_finish()))
    total = {'wall_seconds': time.perf_counter() - wall,
             'cpu_seconds': time.process_time() - cpu}
    if profile:
        profile.disable()
        stats = pstats.Stats(profile)
        rows = []
        for (file, line, name), (primitive, calls, own, cumulative, _) in stats.stats.items():
            if 'mg2mc' in file or 'mc2mb' in file or 'lal_model' in file or 'memory_image' in file:
                rows.append({'file': file, 'line': line, 'function': name,
                             'primitive_calls': primitive, 'calls': calls,
                             'self_seconds': own, 'cumulative_seconds': cumulative})
        rows.sort(key=lambda row: row['self_seconds'], reverse=True)
        (Path(args.directory) / 'profile.json').write_text(json.dumps(rows, indent=2))
    # Hashing and writing deliberately occur after all compilation clocks.
    result = {'kind': 'compile', 'status': 'compiled', 'path': args.path,
              'case': args.case, 'style': args.style, 'stages': stages,
              'total': total, 'mb_bytes': len(raw), 'mb_sha256': digest(raw),
              'mg_bytes': len(source.encode()), 'mg_sha256': digest(source.encode()),
              'bootstrap_code_end': asm.C, 'initialized_source_cells': len(asm.code),
              'profiled': args.profile,
              'clock_scope': 'in-memory stages after imports; excludes source read, hashing, disk I/O and child startup'}
    (Path(args.directory) / 'program.mb').write_bytes(raw)
    return result


def runtime_worker(args):
    from malbolge.core import MalbolgeConfig, SparseMemory, parse_source, run_memory
    raw = (Path(args.directory) / 'program.mb').read_bytes()
    _, inp, expected = cases()[args.case]
    config = MalbolgeConfig.malbolge20()
    stages = []

    def stage(name, fn):
        wall, cpu = time.perf_counter(), time.process_time()
        value = fn()
        stages.append({'stage': name, 'wall_seconds': time.perf_counter() - wall,
                       'cpu_seconds': time.process_time() - cpu})
        return value

    cells = stage('validate', lambda: parse_source(raw, config))
    def initialize():
        memory = SparseMemory(config)
        memory.initialize_source(cells)
        return memory
    memory = stage('initialize', initialize)
    result = stage('execute', lambda: run_memory(memory, config, inp,
                    max_steps=args.max_steps, max_output=4096, eof='sentinel'))
    passed = result.stop_reason == 'terminated' and result.output == expected and result.input_consumed == len(inp)
    return {'kind': 'runtime', 'status': 'passed' if passed else 'failed',
            'stages': stages, 'result': result.to_dict(), 'expected_hex': expected.hex(),
            'input_hex': inp.hex(), 'clock_scope': 'after imports/read; validation, initialization, execution measured independently'}


def child(args, kind, directory, path, case, style):
    argv = ['uv', 'run', '--offline', '--no-sync', 'python', str(Path(__file__).resolve()),
            '--worker', kind, '--directory', str(directory), '--path', path,
            '--case', case, '--style', style, '--baseline', args.baseline,
            '--max-steps', str(args.max_steps)]
    if args.profile:
        argv.append('--profile')
    env = dict(os.environ, UV_CACHE_DIR='/private/tmp/pymalbolge-uv-cache')
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True,
                              text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        return {'kind': kind, 'status': 'child_timeout', 'timeout_seconds': args.timeout,
                'note': 'whole-child timeout; no compile/VM runtime or steps inferred'}
    if proc.returncode:
        return {'kind': kind, 'status': 'child_failure', 'returncode': proc.returncode,
                'stderr': proc.stderr[-4000:]}
    return json.loads(proc.stdout)


def summarize(samples):
    groups = {}
    for sample in samples:
        key = (sample['case'], sample['style'], sample['path'])
        groups.setdefault(key, []).append(sample)
    result = []
    for (case, style, path), rows in groups.items():
        good = [r for r in rows if r['compile']['status'] == 'compiled' and r.get('runtime', {}).get('status') == 'passed']
        item = {'case': case, 'style': style, 'path': path, 'samples': len(rows),
                'passed': len(good), 'statuses': [r.get('runtime', r['compile'])['status'] for r in rows]}
        if good:
            item['compile_median'] = {k: statistics.median(r['compile']['total'][k] for r in good)
                                      for k in ('wall_seconds', 'cpu_seconds')}
            item['execute_median'] = {k: statistics.median(next(s[k] for s in r['runtime']['stages'] if s['stage'] == 'execute') for r in good)
                                      for k in ('wall_seconds', 'cpu_seconds')}
            item['mb_bytes'] = sorted(set(r['compile']['mb_bytes'] for r in good))
            item['mb_sha256'] = sorted(set(r['compile']['mb_sha256'] for r in good))
            item['steps'] = sorted(set(r['runtime']['result']['steps'] for r in good))
        result.append(item)
    return result


def parity(samples):
    groups = {}
    for row in samples:
        groups.setdefault((row['repeat'], row['case'], row['style']), []).append(row)
    result = []
    for (repeat, case, style), rows in groups.items():
        complete = len(rows) == len(PATHS) and all(
            row['compile']['status'] == 'compiled' and row.get('runtime', {}).get('status') == 'passed'
            for row in rows)
        same_image = complete and len(set((row['compile']['mb_bytes'],
            row['compile']['mb_sha256']) for row in rows)) == 1
        same_vm = complete and len(set(json.dumps(row['runtime']['result'], sort_keys=True)
                                      for row in rows)) == 1
        result.append({'repeat': repeat, 'case': case, 'style': style,
                       'complete': complete, 'same_mb_bytes_and_hash': same_image,
                       'same_vm_result_including_steps': same_vm,
                       'passed': same_image and same_vm})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline', default=str(DEFAULT_BASELINE))
    parser.add_argument('--cases', default='hello,echo,repeat,call,generated')
    parser.add_argument('--styles', default='cluster/main')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--max-steps', type=int, default=30000000)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--worker', choices=('compile', 'runtime'))
    parser.add_argument('--directory')
    parser.add_argument('--path', choices=PATHS)
    parser.add_argument('--case', choices=tuple(cases()))
    parser.add_argument('--style', choices=STYLES)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(compile_worker(args) if args.worker == 'compile' else runtime_worker(args)))
        return
    if args.output is None:
        parser.error('--output is required')
    selected_cases = args.cases.split(',')
    styles = args.styles.split(',')
    if args.repeats < 1 or any(c not in cases() for c in selected_cases) or any(s not in STYLES for s in styles):
        parser.error('invalid cases/styles/repeats')
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'command': sys.argv, 'python': sys.version, 'uname': list(os.uname()),
                'logical_cores': os.cpu_count(), 'fingerprints': fingerprints(args),
                'cases': {c: {'mg': cases()[c][0], 'input_hex': cases()[c][1].hex(),
                              'expected_hex': cases()[c][2].hex()} for c in selected_cases},
                'repeats': args.repeats, 'styles': styles, 'paths': list(PATHS),
                'profiled': args.profile, 'timeout_seconds': args.timeout,
                'max_steps': args.max_steps, 'note': 'rotated interleaving; profiles excluded from speed claims; same current VM for all paths'}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    samples = []
    for repeat in range(args.repeats):
        order = PATHS[repeat % len(PATHS):] + PATHS[:repeat % len(PATHS)]
        for case in selected_cases:
            for style in styles:
                for path in order:
                    record = {'repeat': repeat, 'case': case, 'style': style, 'path': path}
                    name = '%02d-%s-%s-%s' % (repeat, case, style.replace('/', '-'), path)
                    with tempfile.TemporaryDirectory(prefix='lower-backend-') as temp:
                        record['compile'] = child(args, 'compile', Path(temp), path, case, style)
                        if record['compile']['status'] == 'compiled':
                            record['runtime'] = child(args, 'runtime', Path(temp), path, case, style)
                        profile = Path(temp) / 'profile.json'
                        if profile.exists():
                            (args.output / (name + '-profile.json')).write_bytes(profile.read_bytes())
                    (args.output / (name + '.json')).write_text(json.dumps(record, indent=2))
                    samples.append(record)
                    print(name + ': ' + record.get('runtime', record['compile'])['status'], flush=True)
    summary = summarize(samples)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    comparisons = parity(samples)
    (args.output / 'parity.json').write_text(json.dumps(comparisons, indent=2))
    if any(row['passed'] != row['samples'] for row in summary) or any(not row['passed'] for row in comparisons):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
