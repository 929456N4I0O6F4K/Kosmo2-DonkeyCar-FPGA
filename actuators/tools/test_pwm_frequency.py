"""Verify actual client commands and pulse units without JTAG hardware."""
import unittest
import re
from unittest.mock import patch
from pca_bench import PcaBench, decode


def client(prescale, version=5):
    bench = PcaBench.__new__(PcaBench)
    state = dict(firmware_version=version, ready=True, error_code=0, expired=True,
                 active_or_shutdown_unconfirmed=False, busy=False, shutdown_pending=False)
    bench.sample = lambda: dict(state)
    bench.idle = lambda: dict(state)
    bench.read = lambda register: prescale
    commands = []
    def command(op, channel=0, data=0):
        commands.append((op, channel, data))
        return dict(state, operation=op, read_data=data & 255)
    bench.command = command
    return bench, commands


class FrequencyTests(unittest.TestCase):
    def test_same_microseconds_different_ticks(self):
        for prescale, ticks, actual in [(121, 307, 1498.16), (101, 368, 1501.44)]:
            bench, commands = client(prescale)
            result = bench.esc_sequence(1500, neutral_only=True)
            self.assertEqual(commands, [(5, 0, ticks), (1, 0, 0)])
            self.assertAlmostEqual(result['nominal_actual_us'], actual)
            self.assertEqual(result['prescale'], prescale)

    def test_steering_uses_actual_readback(self):
        bench, commands = client(101)
        result = bench.pulse(3, 1695)
        self.assertEqual(commands[0], (4, 3, 415))
        self.assertAlmostEqual(result['nominal_actual_us'], 1693.2)

    def test_init_60_requires_v5_and_matching_register(self):
        bench, commands = client(121, version=4)
        with self.assertRaises(ValueError): bench.initialize(60)
        self.assertEqual(commands, [])
        bench, commands = client(121)
        with self.assertRaises(RuntimeError): bench.initialize(60)
        self.assertEqual(commands, [(2, 0, 60)])
        bench, commands = client(101)
        self.assertEqual(bench.initialize(60)['prescale'], 101)

    def test_unexpected_prescale_cannot_drive(self):
        bench, commands = client(30)
        with self.assertRaises(ValueError): bench.esc_sequence(1500, neutral_only=True)
        self.assertEqual(commands, [])

    def test_hold_protocol_duration_and_limits(self):
        for seconds, encoded in [(1,0x1196),(2,0x2196),(5,0x5196)]:
            bench,commands=client(101,version=6)
            result=bench.esc_sequence(1655,duration_seconds=seconds)
            self.assertEqual(commands,[(7,0,encoded),(1,0,0)])
            self.assertEqual(result['throttle_seconds'],seconds)
            self.assertAlmostEqual(result['nominal_actual_us'],1656.48)
        for prescale,version,us,seconds in [(101,5,1655,1),(121,6,1655,1),
                                         (101,6,1660,1),(101,6,1655,3),(101,6,1655,0)]:
            bench,commands=client(prescale,version)
            with self.assertRaises(ValueError): bench.esc_sequence(us,duration_seconds=seconds)
            self.assertEqual(commands,[])

    def test_five_second_hold_allows_full_sequence_and_off_on_failure(self):
        bench,commands=client(101,version=6)
        base=bench.sample()
        states=iter([dict(base,active_or_shutdown_unconfirmed=True,esc_phase=2),
                     dict(base,active_or_shutdown_unconfirmed=True,esc_phase=3),dict(base,esc_phase=0)])
        original=bench.command
        def command(op,channel=0,data=0):
            state=original(op,channel,data)
            return dict(state,active_or_shutdown_unconfirmed=True,esc_phase=1) if op==7 else state
        bench.command=command
        bench.sample=lambda: next(states)
        with patch('pca_bench.time.monotonic',side_effect=[0,5,10.5,11.5]), patch('pca_bench.time.sleep'):
            result=bench.esc_sequence(1655,duration_seconds=5)
        self.assertTrue(result['expiry_and_all_off_verified'])
        self.assertEqual(commands[-1],(1,0,0))
        bench,commands=client(101,version=6)
        original=bench.command
        def fail(op,channel=0,data=0):
            value=original(op,channel,data)
            if op==7: raise RuntimeError('injected command failure')
            return value
        bench.command=fail
        with self.assertRaises(RuntimeError): bench.esc_sequence(1655,duration_seconds=5)
        self.assertEqual(commands[-1],(1,0,0))

    def test_v6_hold_phase_decode(self):
        status=(0x5043<<48)|(6<<40)|(7<<28)|(2<<16)|3
        value=decode(status,0)
        self.assertEqual(value['firmware_version'],6)
        self.assertEqual(value['esc_phase_name'],'throttle')

    def test_off_overwrites_a_stale_cached_control_word(self):
        class InterruptedCommit:
            control=0xff70ffff
            def command(self,text):
                for bit,value in re.findall(r'ProbeOut0\[(\d+)\]\} -value ([01])',text):
                    mask=1<<int(bit)
                    self.control=(self.control & ~mask) | (int(value)<<int(bit))
        bench=PcaBench.__new__(PcaBench)
        bench.control=0
        bench.shell=InterruptedCommit()
        bench.idle=lambda: dict(token=7)
        bench.sample=lambda: dict(token=8,busy=False,shutdown_pending=False,error_code=0)
        bench.command(1)
        self.assertEqual(bench.shell.control,0x08100000)


if __name__ == '__main__':
    unittest.main()
