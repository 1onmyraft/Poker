'''
Write simulated hands in the 1onmyraftpoker text format (7-max, ₮0.10/₮0.10 + ₮0.10 ante,
5% rake capped at ₮1.50, random 40-120bb stacks, occasional straddles).

    python -m sim.generate --hands 500 --hero TAG --out hands.txt
'''
import argparse

from .bots import make_bot, PRESETS
from .handhistory import generate

DEFAULT_TABLE = ['TAG', 'Nervous', 'Scared', 'Station', 'Maniac', 'LAG', 'Nit']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--hands', type=int, default=500)
    ap.add_argument('--hero', default='TAG', help='bot that plays as "Hero"')
    ap.add_argument('--table', default=','.join(DEFAULT_TABLE[1:]),
                    help='the six other bots, comma separated')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--names', choices=['anon', 'bots'], default='anon',
                    help='hashed per-hand names like the sample, or bot names')
    ap.add_argument('--out', default='-')
    a = ap.parse_args(argv)
    kinds = [a.hero] + [k.strip() for k in a.table.split(',')]
    for k in kinds:
        if k not in PRESETS:
            ap.error('unknown bot %s (choose from %s)' % (k, ', '.join(PRESETS)))
    bots = [make_bot(k, '%s%d' % (k, i), seed=a.seed * 100 + i) for i, k in enumerate(kinds)]
    text, _ = generate(bots, a.hands, seed=a.seed, hero_index=0, anonymize=a.names == 'anon')
    if a.out == '-':
        print(text, end='')
    else:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)


if __name__ == '__main__':
    main()
