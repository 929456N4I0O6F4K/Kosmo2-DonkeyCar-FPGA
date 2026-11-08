"""Check delayed collector startup without board access or wall-clock waits."""
import unittest
from unittest.mock import patch

import board_link


class CollectorStartupTests(unittest.TestCase):
    def test_waits_for_delayed_log(self):
        ready = 'backend=pa-uio-ktr1; open http://[::]:8080/\n'
        with patch.object(board_link, 'run', side_effect=['', '', ready]) as run, \
                patch.object(board_link.time, 'sleep') as sleep:
            self.assertEqual(board_link.wait_collector_log(object()), ready)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_preserves_startup_error(self):
        error = 'context deadline exceeded\n'
        with patch.object(board_link, 'run', return_value=error), \
                patch.object(board_link.time, 'sleep') as sleep:
            self.assertEqual(board_link.wait_collector_log(object()), error)
        sleep.assert_not_called()

    def test_bounded_when_process_never_logs(self):
        with patch.object(board_link, 'run', return_value=''), \
                patch.object(board_link.time, 'monotonic', side_effect=[0, 0, 16]), \
                patch.object(board_link.time, 'sleep') as sleep:
            self.assertEqual(board_link.wait_collector_log(object(), timeout=15), '')
        self.assertEqual(sleep.call_count, 1)


if __name__ == '__main__':
    unittest.main()
