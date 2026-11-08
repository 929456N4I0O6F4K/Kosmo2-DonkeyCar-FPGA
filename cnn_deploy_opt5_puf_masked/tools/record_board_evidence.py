"""Record a successful deployment and same-frame model validation in the release."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / 'integration/training'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', required=True, type=Path)
    parser.add_argument('--comparison', required=True, type=Path)
    args = parser.parse_args()
    deployment_path = args.deployment.resolve()
    comparison_path = args.comparison.resolve()
    release_path = TRAIN / 'integration_validation.json'
    release = read(release_path)
    deployment = read(deployment_path)
    comparison = read(comparison_path)
    assert deployment['success'] and not deployment['check_only']
    assert not deployment['no_program'] and not deployment['software_only']
    assert comparison['success'] and not comparison['motion_requested']
    assert deployment['host'] == comparison['host']
    assert comparison['model_sha256'] == release['model_sha256']
    artifacts_path = deployment_path.parent / 'artifacts.json'
    artifacts = read(artifacts_path)
    assert artifacts == release['sha256']
    for name, expected in artifacts.items():
        assert sha(TRAIN / name) == expected
    statuses = sorted(deployment_path.parent.glob('jtag-*/status.json'))
    assert statuses
    diagnostics = read(statuses[-1])
    assert diagnostics['firmware_version'] == release['firmware_version']
    assert diagnostics['camera_ready'] and diagnostics['drive_ready']
    assert not any(diagnostics[k] for k in ('drive_fault', 'shutdown_unconfirmed',
                                          'camera_failed', 'capture_fault', 'transport_fault'))
    frames = comparison['frames']
    assert len(frames) >= 50
    assert len({f['sequence'] for f in frames}) == len(frames)
    assert all(f['fpga_q16'] == f['expected_q16'] for f in frames)
    final = comparison['status_after_comparison']
    assert not final['enabled'] and not final['record_open'] and not final['fault']
    assert final['frame']['flags'] == 0
    assert final['frame']['user/angle'] == final['frame']['user/throttle'] == 0
    assert final['controller']['ready'] and not final['controller']['fault']
    assert not final['controller']['shutdown_unconfirmed']
    assert final['command_ack'] > comparison['status_before']['command_ack']
    video = deployment['verification']
    assert video['frames'] >= 50
    paths = [deployment_path, comparison_path, artifacts_path, statuses[-1]]
    evidence = {
        'success': True, 'host': comparison['host'], 'firmware_version': release['firmware_version'],
        'model_sha256': release['model_sha256'], 'exact_same_frame_predictions': len(frames),
        'max_processing_ms': comparison['max_processing_ms'],
        'video_fps': video['fps'], 'source_sequence_fps': comparison['source_sequence_fps'],
        'capture_drops_during_video': video['status_after']['frame']['source_dropped'] - video['status_before']['frame']['source_dropped'],
        'capture_drops_during_comparison': final['frame']['source_dropped'] - comparison['status_before']['frame']['source_dropped'],
        'final_neutral_standby': True, 'nonzero_actuation_tested': False,
        'evidence_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
    }
    evidence_path = ROOT / 'integration/board_evidence.json'
    evidence_path.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    release.update(volatile_pa_programmed=True, new_model_same_frame_board_verified=True,
                   real_network_video_verified=True, pu_binary_execution_tested=True,
                   physical_network_actuation_tested=False,
                   latest_deployment=deployment_path.relative_to(ROOT).as_posix(),
                   same_frame_comparison=comparison_path.relative_to(ROOT).as_posix(),
                   board_evidence=evidence_path.relative_to(ROOT).as_posix())
    release['reports_sha256'][evidence_path.relative_to(ROOT).as_posix()] = sha(evidence_path)
    release_path.write_text(json.dumps(release, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
