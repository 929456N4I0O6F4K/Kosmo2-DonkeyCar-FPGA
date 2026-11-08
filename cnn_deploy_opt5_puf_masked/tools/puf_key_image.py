"""Write or inspect the puf_key.mem block-ROM image read by rtl/puf_key_store.v."""
import argparse
from pathlib import Path
import re

WIDTH = 144
WORD_BITS = 18
WORD_MASK = (1 << WORD_BITS) - 1
WORDS = 32
MODES = {'capture': 0x2C0D0, 'drive': 0x1D0E0}
# Every ROM output bit takes both values across these words, so synthesis can
# never treat a key bit as constant and change the implementation.
FILLER = [0x2AAAA, 0x15555] * 7 + [0x3C3C3]


def words(mode, binding=0, sign_mask=0):
    if mode not in MODES:
        raise ValueError(f'mode must be one of {sorted(MODES)}')
    for name, value in (('binding', binding), ('sign_mask', sign_mask)):
        if not 0 <= value < 1 << WIDTH:
            raise ValueError(f'{name} must fit in {WIDTH} bits')
    split = lambda value: [(value >> (WORD_BITS*i)) & WORD_MASK for i in range(WIDTH // WORD_BITS)]
    image = split(binding) + split(sign_mask) + [MODES[mode]] + FILLER
    assert len(image) == WORDS
    return image


def write(path, mode, binding=0, sign_mask=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(f'{w:05x}\n' for w in words(mode, binding, sign_mask)), encoding='ascii')


def read(path):
    lines = [l.strip() for l in Path(path).read_text(encoding='ascii').splitlines() if l.strip()]
    if len(lines) != WORDS or not all(re.fullmatch(r'[0-9a-fA-F]{5}', l) for l in lines):
        raise ValueError(f'{path} is not a {WORDS}-word puf_key.mem image')
    image = [int(l, 16) for l in lines]
    if image[17:] != FILLER or any(w > WORD_MASK for w in image):
        raise ValueError(f'{path} has a damaged filler region')
    join = lambda part: sum(w << (WORD_BITS*i) for i, w in enumerate(part))
    mode = next((name for name, code in MODES.items() if code == image[16]), None)
    if mode is None:
        raise ValueError(f'{path} has an unknown mode word {image[16]:05x}')
    return dict(mode=mode, binding=join(image[0:8]), sign_mask=join(image[8:16]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    capture = sub.add_parser('capture', help='write the fail-stopped capture key (no binding)')
    capture.add_argument('output', type=Path)
    show = sub.add_parser('show', help='print the mode and masks of an image')
    show.add_argument('image', type=Path)
    args = parser.parse_args()
    if args.command == 'capture':
        write(args.output, 'capture')
        print(f'Wrote capture key {args.output}')
    else:
        key = read(args.image)
        print(f"mode={key['mode']} binding={key['binding']:036x} sign_mask={key['sign_mask']:036x}")


if __name__ == '__main__':
    main()
