"""Create the opt4 deployment without changing either preceding release."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
OLD = PROJECT / 'cnn_deploy_physical2'
MODEL = PROJECT / 'mypilot1_s2_physical2_opt4'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    marker = ROOT / 'upgrade_origin.json'
    if marker.exists():
        print('Upgrade exists; preserving edits')
        return
    excluded = {'build', 'runs', 'baseline', 'log', 'logbackup', 'prj_tasks',
                '__pycache__', 'bin', 'generated', '.host-deps', 'exports'}
    names = {'integration_validation.json', 'board_evidence.json',
             'original_before_deployment.json', 'source_origin.json', 'prepare_upgrade.py'}
    copied = {}
    for folder in ('rtl', 'sim', 'synthesis', 'integration', 'tools'):
        for path in (OLD / folder).rglob('*'):
            rel = path.relative_to(OLD)
            if not path.is_file() or any(p in excluded for p in rel.parts) or path.name in names:
                continue
            if path.suffix.lower() not in {'.v', '.sv', '.vh', '.py', '.go', '.mod', '.sum', '.md', '.json', '.tcl', '.fdc', '.ps1', '.cmd', '.html', '.js', '.css'}:
                continue
            destination = ROOT / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            copied[rel.as_posix()] = sha(path)
    for name in ('start_cnn.cmd', 'start_cnn.ps1'):
        shutil.copyfile(OLD / name, ROOT / name)
        copied[name] = sha(OLD / name)
    binaries = ROOT / 'integration/training/bin'
    binaries.mkdir(parents=True, exist_ok=True)
    for path in (OLD / 'integration/training/bin').iterdir():
        if path.is_file():
            shutil.copyfile(path, binaries / path.name)
    old_manifest = json.loads((OLD / 'model_manifest.json').read_text(encoding='utf-8'))
    (ROOT / 'previous_model_manifest.json').write_text(json.dumps(old_manifest, indent=2) + '\n')
    config = {
        'model': (MODEL / 'mypilot1_s2_physical_int8.tflite').relative_to(PROJECT).as_posix(),
        'float_model': (MODEL / 'mypilot1_s2_physical.tflite').relative_to(PROJECT).as_posix(),
        'keras_model': (MODEL / 'mypilot1_s2_physical_best.keras').relative_to(PROJECT).as_posix(),
        'training_config': (MODEL / 'train_config.json').relative_to(PROJECT).as_posix(),
        'previous_model': old_manifest['model'],
        'crop': {'top': 25, 'left': 2, 'right': 2, 'height': 95, 'width': 156},
        'recording_archives': 'model/*.zip', 'firmware_version': 11,
        'release': 'camera-cnn-drive-opt4-v11', 'inference': 'single-pass',
    }
    (ROOT / 'deployment_config.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    artifact_names = ['integration/training/bin/kosmo-collect-linux-arm64',
                      'integration/training/build/board/prj_tasks/pnr_1/generate_bitstream/kosmo_training_top.sbit']
    origin = {'previous_root': OLD.name, 'source_sha256': copied,
              'previous_artifacts_sha256': {n: sha(OLD / n) for n in artifact_names},
              'new_model_files_sha256': {p.relative_to(PROJECT).as_posix(): sha(p) for p in MODEL.rglob('*') if p.is_file()}}
    marker.write_text(json.dumps(origin, indent=2) + '\n', encoding='utf-8')
    print(f'Copied {len(copied)} sources; prior releases preserved')


if __name__ == '__main__':
    main()
