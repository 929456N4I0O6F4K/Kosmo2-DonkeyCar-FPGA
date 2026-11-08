"""Persistent local PDS debugger session, with bounded waits and a full transcript."""
import queue
import subprocess
import threading
import time
from pathlib import Path


class Debugger:
    def __init__(self, executable, folder):
        self.lines = queue.Queue()
        self.serial = 0
        self.log = (Path(folder) / 'debugger.log').open('w', encoding='utf-8')
        self.process = subprocess.Popen(
            [str(executable)], cwd=folder, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.log.write(line)
                self.log.flush()
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def command(self, command, timeout=20):
        self.serial += 1
        marker = f'CAMERA_COMMAND_END_{self.serial}'
        self.process.stdin.write(command + '\nputs ' + marker + '\nflush stdout\n')
        self.process.stdin.flush()
        end = time.monotonic() + timeout
        result = []
        while time.monotonic() < end:
            try:
                line = self.lines.get(timeout=max(.01, end-time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError('PDS debugger exited; see debugger.log')
            if marker in line:
                output = ''.join(result)
                if 'E: ' in output:
                    raise RuntimeError(output)
                return output
            result.append(line)
        raise TimeoutError(f'PDS debugger timeout: {command}; see debugger.log')

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('clean\ndbg_disconnect\ndbg_close\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.log.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1] / 'build'
    shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
    try:
        print(shell.command('dbg_help'))
    finally:
        shell.close()
