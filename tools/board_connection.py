"""One board IPv4 setting shared by deployment, SSH and HTTP helpers."""
import ipaddress
import json
import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'training/board_connection.json'


def board_host(override=None):
    value = override or os.environ.get('KOSMO_BOARD_HOST')
    if not value:
        value = json.loads(CONFIG.read_text(encoding='utf-8-sig'))['host']
    try:
        return str(ipaddress.IPv4Address(value))
    except (ipaddress.AddressValueError, TypeError) as error:
        raise ValueError('Board host must be an IPv4 address, e.g. 192.168.43.124') from error


def board_url(host):
    return f'http://{board_host(host)}:8080/'
