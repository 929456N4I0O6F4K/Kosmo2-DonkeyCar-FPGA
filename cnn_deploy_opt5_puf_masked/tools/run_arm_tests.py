"""Run offline Go tests on the real ARM64 CPU; tests do not open MMIO."""
from pathlib import Path
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integration/tools'))
from pu_ssh import connect

def main():
    with connect(os.environ.get('KOSMO_SSH_PASSWORD') or 'root') as client:
        with client.open_sftp() as sftp:
            sftp.put(str(ROOT/'integration/training/bin/collector-tests-linux-arm64'),'/tmp/kosmo-cnn-offline-tests')
            sftp.chmod('/tmp/kosmo-cnn-offline-tests',0o700)
        _,out,err=client.exec_command('/tmp/kosmo-cnn-offline-tests -test.v -test.timeout=90s',timeout=100)
        text=out.read().decode(errors='replace')+err.read().decode(errors='replace')
        folder=ROOT/'integration/training/build';(folder/'arm64-tests.log').write_text(text,encoding='utf-8')
        print(text)
        if out.channel.recv_exit_status()!=0 or '\nPASS\n' not in text:raise RuntimeError('ARM64 offline tests failed')

if __name__=='__main__':main()
