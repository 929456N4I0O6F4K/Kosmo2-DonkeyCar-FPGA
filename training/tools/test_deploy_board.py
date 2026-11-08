"""Offline deployment workflow regressions; no SSH/JTAG or drive commands."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch, Mock

from deploy_board import (Operations, StepError, check_ready, deploy, deploy_software, deployment_lock)
from board_connection import board_host


HEALTHY = {'backend': 'pa-uio-ktr1', 'enabled': False, 'record_open': False, 'fault': '',
           'frame_age_ms': 10, 'frame': {'flags': 0, 'user/angle': 0, 'user/throttle': 0},
           'controller': {'ready': True, 'armed': True, 'fault': False,
                          'shutdown_unconfirmed': False, 'stop': False}}


class FakeOps:
    def __init__(self, isolation=0):
        self.events = []
        self.state = {'isolation': isolation, 'boot_id': 'old', 'magic': 0x3152544b, 'abi': 3}
        self.health = {'firmware_version': 4, 'drive_active': False, 'shutdown_unconfirmed': False}
        self.web = copy.deepcopy(HEALTHY)
        self.errors = []

    def preflight(self, no_program, software_only=False): self.events.append('preflight')
    def inspect(self): self.events.append('inspect'); return self.state
    def status(self, optional=False): return self.web
    def stop(self): self.events.append('stop')
    def diagnostics(self, reset): self.events.append('reset' if reset else 'confirm-off'); return self.health
    def reboot_and_wait(self, boot): self.events.append('reboot')
    def load(self): self.events.append('load')
    def start(self):
        self.events.append('start')
        if self.errors:
            error = self.errors.pop(0)
            if error: raise error
    def note(self, text): self.events.append('notice')
    def wait_ready(self): self.events.append('wait-ready')
    def verify(self): self.events.append('verify'); return {'frames': 100}


class DeploymentTests(unittest.TestCase):
    def test_software_update_uses_no_jtag_reset_or_reboot(self):
        for abi in (2, 3):
            ops = FakeOps(15); ops.state['abi'] = abi
            self.assertEqual(deploy_software(ops), {'frames': 100})
            self.assertEqual(ops.events, ['preflight','inspect','stop','start','wait-ready','verify'])

    def test_software_update_requires_healthy_idle_initialized_link(self):
        for change in ('driving', 'recording', 'stale', 'fault', 'isolated', 'unknown-abi'):
            ops = FakeOps(15)
            if change == 'driving': ops.web['enabled'] = True
            if change == 'recording': ops.web['record_open'] = True
            if change == 'stale': ops.web['frame_age_ms'] = 900
            if change == 'fault': ops.web['controller']['fault'] = True
            if change == 'isolated': ops.state['isolation'] = 0
            if change == 'unknown-abi': ops.state['abi'] = 1
            with self.subTest(change=change), self.assertRaises(RuntimeError): deploy_software(ops)
            self.assertNotIn('stop', ops.events)

    def test_cold_start_does_not_reboot(self):
        ops = FakeOps()
        self.assertEqual(deploy(ops), {'frames': 100})
        self.assertEqual(ops.events, ['preflight', 'inspect', 'stop', 'load', 'start', 'wait-ready', 'verify'])

    def test_warm_reload_confirms_off_before_reboot_and_load(self):
        ops = FakeOps(15)
        deploy(ops)
        self.assertEqual(ops.events, ['preflight', 'inspect', 'stop', 'confirm-off', 'reboot', 'load', 'start', 'wait-ready', 'verify'])

    def test_active_session_is_not_interrupted(self):
        for key in ('enabled', 'record_open'):
            with self.subTest(key=key):
                ops = FakeOps(15); ops.web[key] = True
                with self.assertRaisesRegex(RuntimeError, 'active'):
                    deploy(ops)
                self.assertNotIn('stop', ops.events)

    def test_unreachable_running_session_is_not_interrupted(self):
        ops = FakeOps(15)
        ops.state['collector_running'] = True
        ops.web = None
        with self.assertRaisesRegex(RuntimeError, 'unknown session'):
            deploy(ops)
        self.assertNotIn('stop', ops.events)

    def test_host_override_reaches_every_network_step(self):
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100, host='192.168.43.99')
            with patch.object(ops, 'command') as command:
                for action in ('stop', 'check-isolated', 'prepare-link', 'deploy', 'verify'):
                    ops.link(action)
                    argv = command.call_args.args[1]
                    self.assertEqual(argv[argv.index('--host') + 1], ops.host)
                with patch.object(ops, 'inspect', return_value={'boot_id':'new','isolation':0}), \
                        patch('deploy_board.time.sleep'):
                    ops.reboot_and_wait('old')
                argv = command.call_args.args[1]
                self.assertEqual(argv[argv.index('--host') + 1], ops.host)
            ops.opener = Mock()
            ops.opener.open.return_value = io.StringIO(json.dumps(HEALTHY))
            self.assertEqual(ops.status(), HEALTHY)
            self.assertEqual(ops.opener.open.call_args.args[0], 'http://192.168.43.99:8080/api/status')

    def test_inspection_connects_to_selected_board(self):
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100, host='192.168.43.99')
            with patch('pu_ssh.connect') as connect, patch('board_link.run', side_effect=[
                    'pu-pa-ddr', '0x00300000', '0', 'new-boot', '5.10.0-kosmo-wifi1',
                    '/root/kosmo-training/kosmo-collect\n', 'wlan0']):
                state = ops.inspect()
            self.assertEqual(connect.call_args.kwargs['host'], ops.host)
            self.assertTrue(state['collector_running'])
            self.assertNotIn('magic', state, 'Do not read a mailbox while the PU/PA link is isolated')

    def test_address_precedence_and_invalid_address(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'connection.json'
            config.write_text('{"host":"192.168.43.124"}')
            with patch('board_connection.CONFIG', config), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(board_host(), '192.168.43.124')
                with patch.dict('os.environ', {'KOSMO_BOARD_HOST':'192.168.137.10'}):
                    self.assertEqual(board_host(), '192.168.137.10')
                    self.assertEqual(board_host('192.168.43.99'), '192.168.43.99')
            for value in ('http://192.168.43.124/', '192.168.43.124:8080', '192.168.43.124\n', 'bad'):
                with self.assertRaises(ValueError):
                    board_host(value)

    def test_unknown_live_firmware_is_not_stopped_or_programmed(self):
        ops = FakeOps(15); ops.state['magic'] = 0
        with self.assertRaisesRegex(RuntimeError, 'unknown firmware'):
            deploy(ops)
        self.assertNotIn('stop', ops.events)
        self.assertNotIn('load', ops.events)

    def test_unconfirmed_shutdown_blocks_reset_reboot_and_load(self):
        for key in ('drive_active', 'shutdown_unconfirmed'):
            for no_program in (False, True):
                with self.subTest(key=key, no_program=no_program):
                    ops = FakeOps(15); ops.health[key] = True
                    with self.assertRaisesRegex(RuntimeError, 'shutdown'):
                        deploy(ops, no_program)
                    self.assertFalse({'reset', 'reboot', 'load', 'start'} & set(ops.events))

    def test_no_program_initializes_without_reboot(self):
        ops = FakeOps(15)
        deploy(ops, no_program=True)
        self.assertEqual(ops.events, ['preflight', 'inspect', 'stop', 'confirm-off', 'reset', 'start', 'wait-ready', 'verify'])
        with self.assertRaisesRegex(RuntimeError, 'No initialized'):
            deploy(FakeOps(), no_program=True)

    def test_legacy_abi_requires_full_upgrade(self):
        for abi in (1, 2):
            ops = FakeOps(15); ops.state['abi'] = abi
            with self.assertRaisesRegex(RuntimeError, 'ABI 3'):
                deploy(ops, no_program=True)
            self.assertNotIn('stop', ops.events)
            deploy(ops)
            self.assertIn('reboot', ops.events)

    def test_ack_failure_has_only_one_guarded_recovery(self):
        ops = FakeOps(15)
        ops.errors = [StepError('deploy', 'context deadline exceeded'), StepError('deploy', 'context deadline exceeded')]
        with self.assertRaises(StepError): deploy(ops)
        self.assertEqual(ops.events.count('start'), 2)
        self.assertEqual(ops.events.count('confirm-off'), 2)
        self.assertNotIn('verify', ops.events)

    def test_running_service_or_hardware_failure_is_not_retried(self):
        for output in ('PCA fault', 'backend=pa-uio-ktr1; context deadline exceeded',
                       'initial exposure configuration: context deadline exceeded'):
            ops = FakeOps(); ops.errors = [StepError('deploy', output)]
            with self.assertRaises(StepError): deploy(ops)
            self.assertEqual(ops.events.count('start'), 1)
            self.assertNotIn('reboot', ops.events)

    def test_ready_requires_fresh_video_zero_labels_and_hardware_health(self):
        self.assertTrue(check_ready(HEALTHY))
        for section, key, value in [(None, 'frame_age_ms', 500), ('frame', 'user/throttle', 1),
                                    ('frame', 'user/angle', .1), ('controller', 'armed', False),
                                    ('controller', 'shutdown_unconfirmed', True), ('controller', 'fault', True)]:
            s = copy.deepcopy(HEALTHY)
            (s if section is None else s[section])[key] = value
            self.assertFalse(check_ready(s))

    def test_camera_failure_retains_cause_and_healthy_controller_status(self):
        status = copy.deepcopy(HEALTHY)
        status.update(fault='camera: context deadline exceeded', frame_age_ms=-1, command_ack=722)
        status['frame']['frame_sequence'] = 0
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100)
            with patch.object(ops, 'status', return_value=status), patch.object(ops, 'note'):
                with self.assertRaisesRegex(RuntimeError, 'Collector reports a fault: camera: context deadline exceeded') as raised:
                    ops.wait_ready()
            self.assertIn('Controller fault=False', str(raised.exception))
            saved = json.loads((Path(directory) / 'wait-ready-failure-status.json').read_text())
            self.assertEqual(saved, status)

    def test_hardware_failure_has_its_own_message_and_saved_status(self):
        status = copy.deepcopy(HEALTHY)
        status['controller']['fault'] = True
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100)
            with patch.object(ops, 'status', return_value=status), patch.object(ops, 'note'):
                with self.assertRaisesRegex(RuntimeError, 'Hardware controller reports a fault'):
                    ops.wait_ready()
            self.assertEqual(json.loads((Path(directory) / 'wait-ready-failure-status.json').read_text()), status)

    def test_readiness_timeout_preserves_last_status_after_network_failure(self):
        status = copy.deepcopy(HEALTHY)
        status['frame_age_ms'] = -1
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100)
            with patch.object(ops, 'status', side_effect=[status, urllib.error.URLError('offline')]), \
                    patch.object(ops, 'note'), patch('deploy_board.time.sleep'), \
                    patch('deploy_board.time.monotonic', side_effect=[0, 0, 1, 25]):
                with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                    ops.wait_ready()
            self.assertEqual(json.loads((Path(directory) / 'wait-ready-failure-status.json').read_text()), status)

    def test_readiness_timeout_without_http_status_saves_null(self):
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100)
            with patch.object(ops, 'status', side_effect=urllib.error.URLError('offline')), \
                    patch.object(ops, 'note'), patch('deploy_board.time.sleep'), \
                    patch('deploy_board.time.monotonic', side_effect=[0, 0, 25]):
                with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                    ops.wait_ready()
            self.assertIsNone(json.loads((Path(directory) / 'wait-ready-failure-status.json').read_text()))

    def test_ready_status_does_not_create_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            ops = Operations(Path(directory), 100)
            with patch.object(ops, 'status', return_value=HEALTHY), patch.object(ops, 'note'):
                ops.wait_ready()
            self.assertFalse((Path(directory) / 'wait-ready-failure-status.json').exists())

    def test_corrupted_artifact_rejected_before_any_board_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'integration_validation.json').write_text('{"sha256":{"bin/kosmo-collect-linux-arm64":"wrong"}}')
            (root / 'bin').mkdir(); (root / 'bin/kosmo-collect-linux-arm64').write_bytes(b'changed')
            with patch('deploy_board.ROOT', root):
                with self.assertRaisesRegex(RuntimeError, 'differs'):
                    Operations(root, 100).preflight(True)

    def test_second_deployment_cannot_take_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deploy.lock'
            with deployment_lock(path):
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    with deployment_lock(path): pass
            with deployment_lock(path): pass


if __name__ == '__main__':
    unittest.main()
