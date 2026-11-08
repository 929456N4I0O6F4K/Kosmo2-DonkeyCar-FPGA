"""Joint control gates, fixed pulse commands, and failure/interrupt shutdown."""
import json
import unittest
from unittest.mock import patch

from joint_test import run_console, STARTUP_STEERING
from pca_bench import decode, JOINT_STEERING
from test_pwm_frequency import client


class FakeBench:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.version = 8

    def sample(self):
        return dict(firmware_version=self.version, ready=True, error_code=0, expired=True,
                    active_or_shutdown_unconfirmed=False, busy=False, shutdown_pending=False)

    def initialize(self, frequency):
        self.calls.append(('init', frequency))
        return dict(self.sample(), prescale=101, tick_us=4.08, nominal_frequency_hz=59.8384)

    def command(self, op):
        self.calls.append(('command', op))
        return self.sample()

    def configure_joint_center(self, us):
        self.calls.append(('set-center', us))
        return dict(requested_us=us, ticks=round(us/4.08), output_sent=False)

    def esc_sequence(self, us, **kwargs):
        self.calls.append(('neutral', us) if kwargs.get('neutral_only') else ('solo', us, kwargs.get('duration_seconds')))
        if not kwargs.get('neutral_only') and self.failure is not None:
            raise self.failure
        return dict(requested_us=us, expiry_and_all_off_verified=True)

    def joint_sequence(self, position, moving=False, duration_seconds=2, **kwargs):
        self.calls.append(('joint', position, moving, duration_seconds))
        if self.failure is not None:
            raise self.failure
        return dict(position=position, moving=moving, target_seconds=duration_seconds,
                    steering_us=kwargs.get('steering_us',{'center':1695,'right':1595,'left':1795}[position]),
                    steering_return_us=kwargs.get('center_us',1695),
                    expiry_and_all_off_verified=True)


PREPARE = ['neutral', 'ok', 'steer center', 'ok', 'steer right', 'ok', 'steer left', 'ok']


def console(lines, failure=None, version=8, initial_steering=JOINT_STEERING):
    bench = FakeBench(failure)
    bench.version=version
    report = {}
    iterator = iter([*lines, 'q'])
    snapshots = []
    run_console(bench, report, lambda: snapshots.append(json.loads(json.dumps(report))),
                read_line=lambda _: next(iterator), write=lambda *a, **k: None,
                initial_steering=initial_steering)
    return bench, report, snapshots


class JointConsoleTests(unittest.TestCase):
    def test_latest_startup_profile_does_not_move_or_inherit_confirmations(self):
        bench,report,_=console(['steer center','drive center 0.5'],version=9,initial_steering=None)
        self.assertEqual(bench.calls,[('init',60),('set-center',1745),('command',1)])
        self.assertEqual(report['steering_us'],dict(center=1745,right=1490,left=2020))
        self.assertFalse(report['neutral_confirmed'])
        self.assertTrue(all(not c['success'] for c in report['commands']))

    def test_init_restores_latest_center_and_positions_without_motion(self):
        bench,report,_=console(['set center 1750','init','results'],version=9,initial_steering=None)
        self.assertEqual(report['steering_us'],STARTUP_STEERING)
        self.assertEqual([c for c in bench.calls if c[0]=='set-center'],
                         [('set-center',1745),('set-center',1750),('set-center',1745)])
        self.assertFalse(any(c[0] in ('neutral','solo','joint') for c in bench.calls))

    def test_new_profile_requires_configurable_firmware_and_v8_rejects_extension(self):
        for version in (7,8):
            with self.assertRaises(RuntimeError):console([],version=version,initial_steering=None)
        previous_profile=dict(center=1745,right=1490,left=1990)
        bench,report,_=console(PREPARE+['set right 1470','set left 2010'],version=8,initial_steering=previous_profile)
        self.assertTrue(all(c['success'] for c in report['commands'][:-2]))
        self.assertTrue(all(not c['success'] for c in report['commands'][-2:]))
        self.assertEqual(report['steering_us'],previous_profile)

    def test_outer_expansion_uses_20us_steps_and_requires_each_observation(self):
        lines=PREPARE+['set right 1450','set left 2040','set right 1470',
            'set right 1450','steer right','ok','set right 1450','steer right','ok',
            'set left 2010','steer left','ok','set left 2030','steer left','ok',
            'set left 2040','steer left','ok','set right 1449','set left 2041']
        _,report,_=console(lines,version=9,initial_steering=dict(center=1745,right=1490,left=1990))
        self.assertEqual(report['steering_us'],dict(center=1745,right=1450,left=2040))
        self.assertEqual([c['input'] for c in report['commands'] if not c['success']],
                         ['set right 1450','set left 2040','set right 1450','set right 1449','set left 2041'])
        self.assertEqual(len(report['settings_history']),5)
        for c in report['commands']:
            if c['success'] and c['input'].startswith('steer '):
                self.assertEqual(c['result']['steering_return_us'],1745)

    def test_new_side_clears_drive_and_failure_allows_retreat(self):
        _,report,_=console(PREPARE+['drive center 0.5','ok','set right 1470',
            'drive center 0.5','steer right','fail endpoint reached','set right 1490','drive center 0.5'],
            version=9,initial_steering=None)
        self.assertEqual(report['steering_us']['right'],1490)
        self.assertTrue(all(v==0 for v in report['drive_confirmed_seconds'].values()))
        self.assertFalse(report['commands'][11]['success'])
        self.assertFalse(report['commands'][-1]['success'])
        self.assertFalse(report['neutral_confirmed'])

    def test_startup_and_unconfirmed_commands_cannot_move(self):
        bench, report, _ = console(['ok', 'steer center', 'drive center 0.5'])
        self.assertEqual(bench.calls, [('init', 60), ('command', 1)])
        self.assertTrue(report['shutdown_confirmed'])
        self.assertTrue(all(not c['success'] for c in report['commands']))

    def test_steering_needs_center_and_each_physical_confirmation(self):
        bench, report, _ = console(['neutral', 'ok', 'steer right', 'steer center',
                                    'steer left', 'drive center 0.5'])
        self.assertEqual([c for c in bench.calls if c[0] == 'joint'], [('joint', 'center', False, 2)])
        self.assertEqual(report['steering_confirmed'], [])
        bench, report, _ = console(PREPARE+['drive center 0.5', 'ok'])
        self.assertEqual(set(report['steering_confirmed']), {'center', 'left', 'right'})
        self.assertEqual(report['drive_confirmed_seconds']['center'], .5)

    def test_successful_software_completion_does_not_authorize_longer_motion(self):
        bench, report, _ = console(PREPARE+['drive right 0.5', 'drive center 0.5',
                                           'drive center 1', 'drive left 0.5'])
        self.assertEqual([c for c in bench.calls if c[0] == 'joint' and c[2]],
                         [('joint', 'center', True, .5)])
        self.assertTrue(all(v == 0 for v in report['drive_confirmed_seconds'].values()))

    def test_each_direction_requires_its_own_progression(self):
        bench, report, _ = console(PREPARE+['drive center 0.5', 'ok', 'drive right 1',
            'drive right 0.5', 'ok', 'drive right 1', 'ok', 'drive left 2', 'drive right 2', 'ok'])
        self.assertEqual([c for c in bench.calls if c[0] == 'joint' and c[2]],
            [('joint','center',True,.5),('joint','right',True,.5),
             ('joint','right',True,1),('joint','right',True,2)])
        self.assertEqual(report['drive_confirmed_seconds'], dict(center=.5, right=2, left=0))

    def test_off_init_and_new_neutral_clear_qualifications(self):
        for reset in ['off', 'init', 'neutral']:
            bench, report, _ = console(PREPARE+[reset, 'drive center 0.5'])
            self.assertEqual(report['steering_confirmed'], [])
            self.assertFalse(report['neutral_confirmed'])
            self.assertFalse(any(c[0] == 'joint' and c[2] for c in bench.calls))

    def test_steering_recheck_invalidates_pose_until_confirmed(self):
        _, report, _ = console(PREPARE+['drive center 0.5', 'ok', 'steer right', 'drive center 0.5'])
        self.assertNotIn('right', report['steering_confirmed'])
        self.assertTrue(all(v == 0 for v in report['drive_confirmed_seconds'].values()))
        self.assertFalse(report['commands'][-1]['success'])

    def test_fault_clears_confirmations_and_records_shutdown(self):
        bench, report, _ = console(['neutral', 'ok', 'steer center', 'ok', 'drive center 0.5'],
                                   failure=RuntimeError('I2C timeout'))
        self.assertFalse(report['neutral_confirmed'])
        self.assertEqual(report['steering_confirmed'], [])
        self.assertFalse(report['commands'][-1]['success'])
        self.assertEqual(bench.calls[-1], ('command', 1))

    def test_keyboard_interrupt_during_output_requests_off(self):
        bench, report, _ = console(['neutral', 'ok', 'steer center'], failure=KeyboardInterrupt())
        self.assertTrue(report['interrupted'])
        self.assertEqual(bench.calls[-1], ('command', 1))
        self.assertTrue(report['shutdown_confirmed'])

    def test_malformed_or_excessive_inputs_are_not_forwarded(self):
        bench, report, _ = console(PREPARE+['drive center 5', 'drive right', 'steer 2010',
            'drive center nan', 'drive center -1', 'steer center 2', 'drive center 0.5 extra'])
        self.assertFalse(any(c[0] == 'joint' and c[2] for c in bench.calls))
        self.assertTrue(all(not c['success'] for c in report['commands'][-7:]))

    def test_results_log_preserves_the_state_at_that_time(self):
        _,report,_=console(PREPARE+['results','drive center 0.5','ok'])
        snapshot=next(c['result'] for c in report['commands'] if c['input']=='results')
        self.assertEqual(snapshot['drive_confirmed_seconds']['center'],0)
        self.assertEqual(report['drive_confirmed_seconds']['center'],.5)

    def test_compare_requires_confirmed_neutral_and_center(self):
        bench,report,_=console(['compare solo','neutral','ok','compare solo',
            'steer center','compare center','ok','compare solo','observed no-motion'])
        self.assertEqual([x for x in bench.calls if x[0]=='solo'],[('solo',1655,.5)])
        self.assertFalse(any(x[0]=='joint' and x[2] for x in bench.calls))
        self.assertEqual(report['comparison_observations'][0]['outcome'],'no-motion')

    def test_same_session_solo_center_solo_does_not_promote_drive(self):
        bench,report,_=console(['neutral','ok','steer center','ok',
            'compare solo','observed moving','compare center','observed no-motion',
            'compare solo','observed moving'])
        self.assertEqual([x for x in bench.calls if x[0] in ('solo','joint')],
            [('joint','center',False,2),('solo',1655,.5),('joint','center',True,.5),('solo',1655,.5)])
        self.assertEqual([x['outcome'] for x in report['comparison_observations']],['moving','no-motion','moving'])
        self.assertTrue(all(x==0 for x in report['drive_confirmed_seconds'].values()))
        self.assertEqual(sum(x[0]=='neutral' for x in bench.calls),1)

    def test_comparison_needs_explicit_observation_and_rejects_ok(self):
        bench,report,_=console(['neutral','ok','steer center','ok','compare solo',
            'ok','compare center','observed no-motion','compare center','observed moving'])
        self.assertEqual(len(report['comparison_observations']),2)
        self.assertFalse(report['commands'][5]['success'])
        self.assertFalse(report['commands'][6]['success'])
        self.assertEqual(sum(x[0]=='joint' and x[2] for x in bench.calls),1)

    def test_fail_records_negative_observation_and_revokes_qualification(self):
        bench,report,_=console(['neutral','ok','steer center','ok','steer right',
            'fail right did not return','ok','drive center 0.5','compare solo'])
        self.assertEqual(report['failed_observations'][0]['result']['position'],'right')
        self.assertFalse(report['neutral_confirmed'])
        self.assertFalse(any(x[0]=='joint' and x[2] for x in bench.calls))
        self.assertFalse(any(x[0]=='solo' for x in bench.calls))

    def test_abnormal_comparison_clears_confirmation(self):
        bench,report,_=console(['neutral','ok','steer center','ok','compare solo',
            'observed abnormal','compare center'])
        self.assertFalse(report['neutral_confirmed'])
        self.assertFalse(report['commands'][-1]['success'])

    def test_comparison_cannot_change_pulse_duration_or_pose(self):
        bench,report,_=console(['neutral','ok','steer center','ok',
            'compare solo 1700','compare center 2','compare left','observed moving'])
        self.assertFalse(any(x[0]=='solo' for x in bench.calls))
        self.assertFalse(any(x[0]=='joint' and x[2] for x in bench.calls))
        self.assertTrue(all(not x['success'] for x in report['commands'][-4:]))

    def test_setting_only_changes_configuration_and_requires_previous_pose_confirmation(self):
        bench,report,_=console(['set right 1545','neutral','ok','steer center','ok',
            'steer right','ok','set right 1545','set right 1495'])
        self.assertEqual([c for c in bench.calls if c[0]=='joint'],
                         [('joint','center',False,2),('joint','right',False,2)])
        self.assertFalse(report['commands'][0]['success'])
        self.assertFalse(report['commands'][-1]['success'])
        self.assertEqual(report['steering_us']['right'],1545)
        self.assertNotIn('right',report['steering_confirmed'])

    def test_new_angle_invalidates_drive_progress_and_requires_a_fresh_steer_check(self):
        _,report,_=console(PREPARE+['drive center 0.5','ok','results','set right 1545',
            'drive center 1','drive right 0.5','steer right','ok','drive right 1',
            'drive center 0.5','ok','drive right 0.5','ok'])
        self.assertFalse(report['commands'][12]['success'])
        self.assertFalse(report['commands'][13]['success'])
        moved=[c['result'] for c in report['commands'] if c['input']=='drive right 0.5' and c['success']]
        self.assertEqual(len(moved),1)
        self.assertEqual(moved[0]['steering_us'],1545)
        snapshot=next(c['result'] for c in report['commands'] if c['input']=='results')
        self.assertEqual(snapshot['steering_us']['right'],1595)
        self.assertEqual(report['drive_confirmed_seconds']['right'],.5)

    def test_both_sides_expand_in_confirmed_steps_and_enforce_limits(self):
        lines=PREPARE.copy()
        for side,values in [('right',[1545,1495,1490]),('left',[1845,1895,1945,1990])]:
            for value in values:lines.extend([f'set {side} {value}',f'steer {side}','ok'])
        lines+=['set right 1489','set left 1991','set center 1751','set left 1939']
        _,report,_=console(lines)
        self.assertEqual(report['steering_us'],dict(center=1695,right=1490,left=1990))
        self.assertEqual(len(report['settings_history']),7)
        self.assertTrue(all(not c['success'] for c in report['commands'][-4:]))

    def test_can_reduce_angle_after_a_failed_observation(self):
        _,report,_=console(PREPARE+['set right 1545','steer right','fail return incomplete',
                                   'set right 1595','steer right'])
        self.assertEqual(report['steering_us']['right'],1595)
        self.assertTrue(report['commands'][-2]['success'])
        self.assertFalse(report['commands'][-1]['success'])
        self.assertFalse(report['neutral_confirmed'])

    def test_v7_can_use_default_poses_but_cannot_change_them(self):
        _,report,_=console(PREPARE+['set right 1545'],version=7)
        self.assertTrue(all(c['success'] for c in report['commands'][:-1]))
        self.assertFalse(report['commands'][-1]['success'])
        self.assertEqual(report['steering_us']['right'],1595)

    def test_center_change_clears_all_pose_and_drive_checks_but_keeps_esc_neutral(self):
        bench,report,_=console(PREPARE+['drive center 0.5','ok','set center 1705',
            'drive center 0.5','steer right','steer center','ok','steer right','ok',
            'steer left','ok','drive center 0.5','ok'])
        self.assertIn(('set-center',1705),bench.calls)
        self.assertFalse(report['commands'][11]['success'])
        self.assertFalse(report['commands'][12]['success'])
        self.assertTrue(report['neutral_confirmed'])
        self.assertEqual(report['steering_us']['center'],1705)
        self.assertEqual(report['drive_confirmed_seconds']['center'],.5)
        for c in report['commands'][13:]:
            if c['input'].startswith(('steer ','drive ')):
                self.assertEqual(c['result']['steering_return_us'],1705)

    def test_center_limits_steps_pending_and_default_reset(self):
        bench,report,_=console(['set center 1706','set center 1649','set center 1751',
            'set center 1705','neutral','set center 1710','ok','init','results'])
        self.assertTrue(all(not c['success'] for c in report['commands'][:3]))
        self.assertFalse(report['commands'][5]['success'])
        self.assertEqual([c for c in bench.calls if c[0]=='set-center'],[('set-center',1705)])
        self.assertEqual(report['steering_us'],dict(center=1695,right=1595,left=1795))

    def test_center_can_be_corrected_after_fail_and_comparison_uses_new_center(self):
        _,report,_=console(['neutral','ok','steer center','fail needs left',
            'set center 1705','neutral','ok','steer center','ok',
            'compare center','observed moving'])
        self.assertEqual(report['failed_observations'][0]['reason'],'needs left')
        self.assertEqual(report['comparison_observations'][0]['result']['steering_return_us'],1705)

    def test_center_cannot_cross_current_side_position(self):
        _,report,_=console(['set left 1745','set left 1705','set center 1705'])
        self.assertTrue(report['commands'][0]['success'])
        self.assertTrue(report['commands'][1]['success'])
        self.assertFalse(report['commands'][2]['success'])
        self.assertEqual(report['steering_us']['center'],1695)


class JointProtocolTests(unittest.TestCase):
    def test_v9_endpoints_with_selected_center_and_return(self):
        for position,us,ticks in [('right',1450,355),('right',1470,360),
                                 ('left',2010,493),('left',2040,500)]:
            for moving in [False,True]:
                bench,calls=client(101,9)
                result=bench.joint_sequence(position,moving,2,steering_us=us,center_us=1745)
                self.assertEqual(calls,[(11,3,428),(9 if moving else 8,0,2<<12|ticks),(1,0,0)])
                self.assertEqual(result['steering_return_us'],1745)
                self.assertEqual(result['steering_return_ticks'],428)
                self.assertEqual(result['neutral_after_seconds'],1)
        for position,us in [('right',1449),('left',2041)]:
            bench,calls=client(101,9)
            with self.assertRaises(ValueError):bench.joint_sequence(position,steering_us=us,center_us=1745)
            self.assertEqual(calls,[])

    def test_return_remains_one_second_for_both_modes_and_versions(self):
        for version,moving in [(8,False),(8,True),(7,False)]:
            bench,calls=client(101,version)
            result=bench.joint_sequence('right',moving,2)
            self.assertEqual(result['neutral_after_seconds'],1)
            self.assertEqual(result['neutral_us'],1550)
            self.assertEqual(result['steering_return_us'],1695)

    def test_v8_custom_steering_widths_and_old_version_guard(self):
        for position,us,ticks in [('right',1490,365),('right',1545,379),
                                  ('left',1845,452),('left',1990,488)]:
            bench,calls=client(101,8)
            result=bench.joint_sequence(position,True,.5,steering_us=us)
            self.assertEqual(calls,[(11,3,415),(9,0,ticks),(1,0,0)])
            self.assertEqual(result['steering_us'],us)
            self.assertEqual(result['throttle_us'],1655)
            self.assertEqual(result['steering_return_ticks'],415)
        for position,us,version in [('right',1489,8),('left',1991,8),('center',1700,8),
                                    ('right',1800,8),('left',1500,8),('right',1490,7)]:
            bench,calls=client(101,version)
            with self.assertRaises(ValueError):bench.joint_sequence(position,True,.5,steering_us=us)
            self.assertEqual(calls,[])

    def test_center_configuration_is_no_motion_and_reasserted_for_each_joint_sequence(self):
        bench,calls=client(101,8)
        config=bench.configure_joint_center(1705)
        self.assertEqual(calls,[(11,3,418)])
        self.assertFalse(config['output_sent'])
        calls.clear()
        result=bench.joint_sequence('center',center_us=1705)
        self.assertEqual(calls,[(11,3,418),(8,0,2<<12|418),(1,0,0)])
        self.assertEqual(result['steering_return_ticks'],418)
        self.assertEqual(result['steering_us'],1705)

    def test_center_configuration_rejects_bad_ack_and_unsuitable_state(self):
        for prescale,version in [(121,8),(101,7)]:
            bench,calls=client(prescale,version)
            with self.assertRaises((ValueError,RuntimeError)):bench.configure_joint_center(1705)
            self.assertEqual(calls,[])
        bench,calls=client(101,8)
        state=bench.idle()
        bench.idle=lambda:dict(state,active_or_shutdown_unconfirmed=True)
        bench.read=lambda reg:self.fail('Active configuration must not even read PCA')
        with self.assertRaises(RuntimeError):bench.configure_joint_center(1705)
        self.assertEqual(calls,[])
        bench,calls=client(101,8)
        original=bench.command
        bench.command=lambda op,channel=0,data=0:dict(original(op,channel,data),read_data=0)
        with self.assertRaises(RuntimeError):bench.joint_sequence('center',center_us=1705)
        self.assertEqual(calls,[(11,3,418),(1,0,0)])

    def test_fixed_positions_and_duration_encoding(self):
        for position,ticks in [('center',415),('right',391),('left',440)]:
            for moving,seconds,code in [(False,2,2),(True,.5,0),(True,1,1),(True,2,2)]:
                bench,calls = client(101,7)
                result=bench.joint_sequence(position,moving,seconds)
                self.assertEqual(calls,[(9 if moving else 8,0,code<<12|ticks),(1,0,0)])
                self.assertEqual(result['steering_ticks'],ticks)
                self.assertEqual(result['throttle_us'],1655 if moving else 1550)
                self.assertEqual(result['neutral_us'],1550)

    def test_wrong_firmware_frequency_position_and_duration_rejected(self):
        for prescale,version,position,moving,seconds in [(101,6,'center',True,.5),
                (121,7,'center',True,.5),(101,7,'other',True,.5),
                (101,7,'center',True,5),(101,7,'center',False,.5)]:
            bench,calls=client(prescale,version)
            with self.assertRaises((ValueError,RuntimeError)):
                bench.joint_sequence(position,moving,seconds)
            self.assertEqual(calls,[])

    def test_command_failure_interrupt_and_deadline_request_off(self):
        for failure in (RuntimeError('I2C'), KeyboardInterrupt()):
            bench,calls=client(101,7)
            original=bench.command
            def command(op,channel=0,data=0):
                state=original(op,channel,data)
                if op==9: raise failure
                return state
            bench.command=command
            with self.assertRaises(type(failure)): bench.joint_sequence('left',True,.5)
            self.assertEqual(calls[-1],(1,0,0))
        bench,calls=client(101,7)
        original=bench.command
        def running(op,channel=0,data=0):
            state=original(op,channel,data)
            return dict(state,active_or_shutdown_unconfirmed=True,esc_phase=2) if op==9 else state
        bench.command=running
        with patch('pca_bench.time.monotonic',side_effect=[0,30]):
            with self.assertRaises(TimeoutError): bench.joint_sequence('right',True,2)
        self.assertEqual(calls[-1],(1,0,0))

    def test_phase_decode(self):
        for op in (8,9):
            value=decode((0x5043<<48)|(7<<40)|(op<<28)|(3<<16)|3,0)
            self.assertEqual(value['esc_phase_name'],'neutral-after')


if __name__ == '__main__':
    unittest.main()
