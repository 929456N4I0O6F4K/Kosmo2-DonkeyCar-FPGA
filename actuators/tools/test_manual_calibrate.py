"""Exercise console bounds, channel routing, result recording and exit cleanup."""
import unittest
from manual_calibrate import run_console


class FakeBench:
    def __init__(self):
        self.commands = []
        self.pulses = []
        self.fail_pulse = False

    def sample(self):
        return dict(firmware_version=2, ready=True, error_code=0, busy=False,
                    shutdown_pending=False, active_or_shutdown_unconfirmed=False)

    def command(self, op):
        self.commands.append(op)
        return self.sample()

    def pulse(self, channel, value):
        self.pulses.append((channel, value))
        if self.fail_pulse:
            raise RuntimeError('injected I2C fault')
        ticks = round(value*25/122)
        return dict(channel=channel, requested_us=value, ticks=ticks, nominal_actual_us=ticks*122/25)


class ConsoleTests(unittest.TestCase):
    def run_commands(self, lines, bench=None):
        bench = bench or FakeBench()
        iterator = iter(lines)
        report = {}
        saves = []
        def read(_):
            value = next(iterator)
            if isinstance(value, BaseException):
                raise value
            return value
        run_console(bench, report, lambda: saves.append(True), read_line=read, write=lambda *a, **k: None)
        self.assertTrue(report['shutdown_confirmed'])
        self.assertEqual(bench.commands[-1], 1)
        self.assertTrue(saves)
        return report, bench

    def test_units_steps_channel_and_marks(self):
        report, bench = self.run_commands(['center', '400', '2500', '2200',
                                          '1700', 'center', '-25', 'left', '+50', 'right', 'q'])
        self.assertEqual(bench.pulses, [(3, 1700), (3, 1675), (3, 1725)])
        self.assertTrue(report['three_points_consistent'])
        self.assertEqual(report['marks']['center']['requested_us'], 1700)
        self.assertTrue(all(not entry['success'] for entry in report['commands'][:4]))

    def test_wider_range_and_five_hundred_microsecond_steps(self):
        report, bench = self.run_commands(['1450', '1200', '+500', '+500', '2586',
                                          '2587', '1199', '2000', 'q'])
        self.assertEqual(bench.pulses, [(3, 1450), (3, 1200), (3, 1700), (3, 2200), (3, 2586)])
        self.assertTrue(all(not entry['success'] for entry in report['commands'][-3:]))

    def test_no_pulse_on_start_or_interrupt(self):
        report, bench = self.run_commands([KeyboardInterrupt()])
        self.assertEqual(bench.pulses, [])
        self.assertTrue(report['interrupted'])

    def test_fault_is_not_recorded_as_calibration(self):
        bench = FakeBench()
        bench.fail_pulse = True
        report, bench = self.run_commands(['1700', 'center', 'q'], bench)
        self.assertEqual(report['marks'], {})
        self.assertTrue(all(not entry['success'] for entry in report['commands']))


if __name__ == '__main__':
    unittest.main()
