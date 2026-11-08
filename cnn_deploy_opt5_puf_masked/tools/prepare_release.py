"""Bind the new model, simulations and complete placed firmware to a release."""
from pathlib import Path
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / 'integration/training'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_hashes(base, hashes):
    for name, expected in hashes.items():
        if digest(base / name) != expected:
            raise RuntimeError('Input changed: ' + str(base / name))


def main():
    origin = read(ROOT / 'upgrade_origin.json')
    previous = ROOT.parent / origin['previous_root']
    check_hashes(previous, origin['source_sha256'])
    check_hashes(previous, origin['previous_artifacts_sha256'])
    check_hashes(ROOT.parent, origin['new_model_files_sha256'])
    model = read(ROOT / 'model_manifest.json')
    config = read(ROOT / 'deployment_config.json')
    assert digest(ROOT.parent / config['model']) == model['model_sha256']
    comparison = read(ROOT / 'build/model_comparison.json')
    assert comparison['new']['model_sha256'] == model['model_sha256']
    assert comparison['same_geometry_and_input_quantization']
    assert comparison['new_output_scale_q30'] == model['output_quantization']['scale_q30']
    quantization = comparison['new']['outputs'][0]
    assert quantization['scale'] == model['output_quantization']['scale']
    assert quantization['zero_point'] == model['output_quantization']['zero_point']
    # Both simulation runs must use the currently exported ROMs and vectors.
    reports = [ROOT / 'build/sim/validation.json', TRAIN / 'build/cnn-bridge-sim/validation.json']
    for report in reports:
        result = read(report)
        assert result['success']
        check_hashes(ROOT, result['source_sha256'])
        for folder in (ROOT / 'rtl/generated', ROOT / 'sim/generated'):
            for path in folder.iterdir():
                if path.suffix in ('.mem', '.vh'):
                    assert digest(path) == digest(report.parent / path.name), str(path)
    simulation = read(reports[0])
    assert simulation['model_sha256'] == model['model_sha256']
    evaluation_path = ROOT / 'build/model_evaluation.json'
    evaluation = read(evaluation_path)
    assert evaluation['model_sha256'] == model['model_sha256']
    regressions_path = ROOT / 'build/deployment_regressions.json'
    regressions = read(regressions_path)
    assert regressions['success'] and regressions['tests'] == 26
    check_hashes(ROOT, regressions['source_sha256'])
    output = TRAIN / 'build/board'
    check_hashes(ROOT, read(output / 'source_sha256.json'))
    assert (output / 'build-validation.txt').read_text().strip() == 'INTEGRATED FPGA BUILD PASS'
    assert 'TRAINING_BOARD_BUILD_FINISHED' in (output / 'build.log').read_text()
    timing_path = output / 'prj_tasks/pnr_1/report_timing/kosmo_training_top.rtr'
    timing = timing_path.read_text()
    assert re.search(r'Design Summary\s*:\s*All Constraints Met\.', timing)
    performance = re.search(r'sysclk_50\s+50\.0000 MHz\s+([\d.]+) MHz\s+20\.0000\s+([\d.]+)\s+([\d.]+)', timing)
    assert performance
    resource_path = output / 'prj_tasks/pnr_1/place_route/kosmo_training_top.ror'
    resources = resource_path.read_text().split('Device Utilization Summary :')[1]
    counts = {}
    group = ''
    for line in resources.splitlines():
        cells = [c.strip() for c in line.split('|')]
        if len(cells) < 5 or not cells[2].isdigit() or not cells[3].isdigit():
            continue
        key, used, available = cells[1:4]
        if key in ('CLMA', 'CLMS'):
            group = key
        if key in ('+ LUT', '+ FF'):
            counts[group + '.' + key[2:]] = {'used': int(used), 'available': int(available)}
        elif key in ('+ DRM36K', '+ DRM18K', '+ APM'):
            counts[key[2:]] = {'used': int(used), 'available': int(available)}
    # The collector/UI are byte-for-byte unchanged. Preserve prior evidence with
    # explicit provenance, rather than claiming these tests ran on the new board.
    for path in (previous / 'integration/training').rglob('*'):
        if path.is_file() and (path.suffix in ('.go', '.mod', '.sum') or 'web' in path.parts):
            if any(part in ('build', 'runs', 'bin') for part in path.relative_to(previous).parts):
                continue
            current = ROOT / path.relative_to(previous)
            assert digest(current) == digest(path), str(current)
    binary = 'bin/kosmo-collect-linux-arm64'
    assert digest(TRAIN / binary) == origin['previous_artifacts_sha256']['integration/training/' + binary]
    prior_release = read(previous / 'integration/training/integration_validation.json')
    assert prior_release['model_sha256'] == comparison['previous']['model_sha256']
    evidence = ROOT / 'build/inherited-software-evidence'
    evidence.mkdir(exist_ok=True)
    inherited = {}
    for source in (previous / 'build/inherited-software-evidence').iterdir():
        if source.is_file():
            name = source.relative_to(previous).as_posix()
            expected = digest(source)
            expected_prior = prior_release['go_and_browser_validation']['reports_sha256']
            assert expected in expected_prior.values(), 'Inherited report no longer matches prior release: ' + name
            shutil.copyfile(source, evidence / source.name)
            inherited[name] = expected
    assert inherited, 'Missing inherited software evidence'
    artifacts = [binary, 'build/board/prj_tasks/pnr_1/generate_bitstream/kosmo_training_top.sbit']
    reports += [timing_path, resource_path, evaluation_path, regressions_path, ROOT / 'build/model_comparison.json']
    result = {
        'release': config['release'], 'firmware_version': config['firmware_version'],
        'inference': config['inference'],
        'abi': 4, 'supported_transport_abis': [4], 'puf': False,
        'original_model_unchanged': True, 'previous_release_unchanged': True,
        'model_sha256': model['model_sha256'], 'output_quantization': model['output_quantization'],
        'rtl_integration': 'passed', 'rtl_processing_ms_at_50mhz': simulation['processing_ms_at_50mhz'],
        'deployment_regressions': {'passed': regressions['tests'], 'hardware_access': False},
        'go_and_browser_validation': {'status': 'inherited; identical source and ARM64 binary',
                                    'from': previous.name, 'reports_sha256': inherited},
        'pds_timing': 'All Constraints Met', 'clock_mhz': 50,
        'estimated_max_mhz': float(performance[1]), 'setup_slack_ns': float(performance[3]),
        'resources': counts, 'volatile_pa_programmed': False,
        'physical_network_actuation_tested': False, 'new_model_same_frame_board_verified': False,
        'evaluation_scope': '192 images from 24 old recording archives; not physicaldata2 held-out accuracy',
        'sha256': {name: digest(TRAIN / name) for name in artifacts},
        'reports_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in reports},
    }
    target = TRAIN / 'integration_validation.json'
    if target.exists() and read(target).get('volatile_pa_programmed'):
        raise RuntimeError('Existing board evidence: do not overwrite a deployed release manifest')
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
