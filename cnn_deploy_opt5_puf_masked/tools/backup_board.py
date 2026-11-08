"""Preserve the pre-CNN board executable/settings without changing the board."""
from pathlib import Path
import os
import json
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integration/tools'))
from pu_ssh import connect,BOARD_HOST


def main():
    folder=ROOT/'runs/pre-cnn-board-backup';folder.mkdir(parents=True,exist_ok=True)
    if (folder/'manifest.json').exists():
        print('Existing pre-CNN board backup retained');return
    result={'host':BOARD_HOST,'files':{}}
    with connect(os.environ.get('KOSMO_SSH_PASSWORD') or 'root') as client:
        with client.open_sftp() as sftp:
            for name in ['kosmo-collect','steering.json','exposure.json','collector.log']:
                target=folder/name;sftp.get('/root/kosmo-training/'+name,str(target))
                result['files'][name]=hashlib.sha256(target.read_bytes()).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original board software/settings saved:',folder)


if __name__=='__main__':main()
