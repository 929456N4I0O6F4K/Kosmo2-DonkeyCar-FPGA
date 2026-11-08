"""Console gate, numeric units, failure recovery and recording; no hardware."""
import unittest
from esc_calibrate import run_console
from pca_bench import pwm_timing


class FakeBench:
    def __init__(self):
        self.commands = []
        self.sequences = []
        self.fail_trial = False
        self.prescale = 121
        self.initialized_frequencies = []
        self.version = 3
        self.durations = []
        self.fail_duration = None

    def sample(self):
        return dict(firmware_version=self.version, ready=True, error_code=0, busy=False,
                    shutdown_pending=False, active_or_shutdown_unconfirmed=False)

    def command(self, op):
        self.commands.append(op)
        return self.sample()

    def initialize(self, frequency=50):
        self.initialized_frequencies.append(frequency)
        self.prescale = 101 if frequency == 60 else 121
        return dict(self.command(2), **pwm_timing(self.prescale))

    def esc_sequence(self, us, neutral_only=False, progress=None, duration_seconds=.5):
        self.sequences.append((us, neutral_only))
        if not neutral_only:
            self.durations.append(duration_seconds)
        if (self.fail_trial or self.fail_duration == duration_seconds) and not neutral_only:
            raise RuntimeError('injected I2C fault')
        if progress:
            progress('neutral-before')
            if not neutral_only:
                progress('throttle'); progress('neutral-after')
            progress('off/idle')
        timing = pwm_timing(self.prescale)
        ticks = round(us/timing['tick_us'])
        return dict(channel=0, requested_us=us, ticks=ticks, nominal_actual_us=ticks*timing['tick_us'], **timing,
                    neutral_only=neutral_only, throttle_seconds=0 if neutral_only else duration_seconds,
                    expiry_and_all_off_verified=True)


class ConsoleTests(unittest.TestCase):
    def run_commands(self, lines, bench=None, frequency=50, **options):
        bench = bench or FakeBench()
        iterator = iter(lines)
        report = {}
        def read(_):
            value = next(iterator)
            if isinstance(value, BaseException):
                raise value
            return value
        run_console(bench, report, lambda: None, read_line=read, write=lambda *a, **k: None, frequency=frequency, **options)
        self.assertTrue(report['shutdown_confirmed'])
        self.assertEqual(bench.commands[-1], 1)
        return report, bench

    def test_no_output_on_start_and_no_bypass(self):
        report, bench = self.run_commands(['ok', '+5', 'start', 'q'])
        self.assertEqual(bench.sequences, [])
        self.assertTrue(all(not entry['success'] for entry in report['commands']))

    def test_units_steps_confirmation_and_marks(self):
        report, bench = self.run_commands(['neutral', '+5', 'ok', '422', '1600',
            '+5', 'start', '+5', 'slow', 'note forward and slow', 'q'])
        self.assertEqual(bench.sequences, [(1500, True), (1505, False), (1510, False)])
        self.assertTrue(report['neutral_confirmed'])
        self.assertEqual(report['marks']['start']['requested_us'], 1505)
        self.assertEqual(report['marks']['slow']['neutral_us'], 1500)

    def test_neutral_change_and_off_revoke_confirmation(self):
        report, bench = self.run_commands(['neutral', 'ok', '+5', 'start', 'neutral 1490',
            '+5', 'ok', '+5', 'off', '+5', 'q'])
        self.assertEqual(bench.sequences, [(1500, True), (1505, False), (1490, True), (1495, False)])
        self.assertEqual(report['marks'], {})
        self.assertFalse(report['neutral_confirmed'])

    def test_fault_not_marked_and_requires_reconfirmation(self):
        bench = FakeBench(); bench.fail_trial = True
        report, bench = self.run_commands(['neutral', 'ok', '+5', 'start', '+5', 'q'], bench)
        self.assertEqual(bench.sequences, [(1500, True), (1505, False)])
        self.assertEqual(report['marks'], {})
        self.assertFalse(report['neutral_confirmed'])

    def test_neutral_cannot_be_marked_as_motion(self):
        report, bench = self.run_commands(['neutral', 'ok', '1500', 'start', 'q'])
        self.assertEqual(report['marks'], {})

    def test_interrupt_exits_with_off(self):
        report, bench = self.run_commands([KeyboardInterrupt()])
        self.assertTrue(report['interrupted'])
        self.assertEqual(bench.sequences, [])

    def test_60hz_marks_use_selected_timing_and_reinit_keeps_frequency(self):
        report, bench = self.run_commands(['neutral', 'ok', '1500', 'start',
            '+5', 'slow', 'init', '+5', 'q'], frequency=60)
        self.assertEqual(bench.initialized_frequencies, [60, 60])
        self.assertEqual(report['pwm_timing']['prescale'], 101)
        self.assertNotIn('start', report['marks'])
        mark = report['marks']['slow']
        self.assertEqual(mark['neutral_ticks'], 368)
        self.assertEqual(mark['ticks'], 369)
        self.assertAlmostEqual(mark['neutral_nominal_actual_us'], 1501.44)
        self.assertFalse(report['commands'][-1]['success'])

    def test_hold_requires_confirmation_and_order_then_records_duration(self):
        bench = FakeBench(); bench.version = 6
        report, bench = self.run_commands(['hold 0.5', 'neutral', 'ok', 'hold 5',
            'hold 0.5', 'hold 2', 'hold 1', 'hold 2', 'hold 5', 'slow', 'q'],
            bench, frequency=60, neutral_us=1550)
        self.assertEqual(bench.durations, [.5, 1, 2, 5])
        self.assertEqual(bench.sequences, [(1550, True)]+[(1655, False)]*4)
        self.assertEqual(report['hold_completed_seconds'], 5)
        self.assertEqual(report['marks']['slow']['throttle_seconds'], 5)
        self.assertEqual(report['marks']['slow']['neutral_ticks'], 380)
        self.assertEqual(report['marks']['slow']['ticks'], 406)

    def test_hold_conditions_and_duration_syntax_cannot_be_bypassed(self):
        for version, frequency, neutral, maximum in [(5,60,1550,1800), (6,50,1550,1800),
                                                     (6,60,1500,1800), (6,60,1550,1600)]:
            bench=FakeBench(); bench.version=version
            report, bench=self.run_commands(['neutral','ok','hold 0.5','q'], bench,
                frequency=frequency, neutral_us=neutral, maximum=maximum)
            self.assertEqual(bench.durations, [])
        bench=FakeBench(); bench.version=6
        report, bench=self.run_commands(['neutral','ok','hold','hold 0','hold 3',
            'hold 1 1700','hold nan','q'],bench,frequency=60,neutral_us=1550)
        self.assertEqual(bench.durations, [])

    def test_hold_progress_reset_by_normal_trial_and_reinitialization(self):
        bench=FakeBench(); bench.version=6
        report,bench=self.run_commands(['neutral','ok','hold 0.5','hold 1',
            '+0','hold 2','hold 0.5','init','neutral','ok','hold 1','q'],
            bench,frequency=60,neutral_us=1550)
        self.assertEqual(bench.durations,[.5,1,.5,.5])
        self.assertEqual(report['hold_completed_seconds'],0)

    def test_hold_fault_revokes_confirmation_and_progress(self):
        bench=FakeBench(); bench.version=6; bench.fail_duration=1
        report,bench=self.run_commands(['neutral','ok','hold 0.5','hold 1','hold 0.5','slow','q'],
            bench,frequency=60,neutral_us=1550)
        self.assertEqual(bench.durations,[.5,1])
        self.assertFalse(report['neutral_confirmed'])
        self.assertEqual(report['hold_completed_seconds'],0)
        self.assertEqual(report['marks'],{})

    def test_keyboard_interrupt_during_hold_exits_with_off(self):
        class InterruptedBench(FakeBench):
            def esc_sequence(self,*args,**kwargs):
                if kwargs.get('duration_seconds')==1:
                    raise KeyboardInterrupt()
                return super().esc_sequence(*args,**kwargs)
        bench=InterruptedBench(); bench.version=6
        report,bench=self.run_commands(['neutral','ok','hold 0.5','hold 1'],
            bench,frequency=60,neutral_us=1550)
        self.assertTrue(report['interrupted'])
        self.assertEqual(bench.commands[-1],1)


if __name__ == '__main__':
    unittest.main()
