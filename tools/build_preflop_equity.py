'''
Precompute the 169 x 169 all-in preflop equity table (hand class vs hand class) used by
the push/fold solver. Each matchup averages over random compatible suit combinations,
so card removal between the two hands is included. Takes a few minutes on 4 cores.

    python tools/build_preflop_equity.py [trials]
'''
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.cards import DECK, PF_ORDER, evaluate      # noqa: E402
from sim.ranges import COMBOS, COMBO_CLASS          # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources',
                   'preflop_equity.json')
CLASS_COMBOS = {k: [c for c, kc in zip(COMBOS, COMBO_CLASS) if kc == k] for k in PF_ORDER}


def row(args):
    i, trials = args
    rng = random.Random(1000 + i)
    a_cls = PF_ORDER[i]
    out = {}
    for j in range(i, len(PF_ORDER)):
        b_cls = PF_ORDER[j]
        won = 0.0
        n = 0
        while n < trials:
            a = rng.choice(CLASS_COMBOS[a_cls])
            b = rng.choice(CLASS_COMBOS[b_cls])
            if len({a[0], a[1], b[0], b[1]}) < 4:
                continue                                   # card conflict: resample
            rest = [c for c in DECK if c not in a and c not in b]
            board = rng.sample(rest, 5)
            va, vb = evaluate(list(a) + board), evaluate(list(b) + board)
            won += 1.0 if va > vb else (0.5 if va == vb else 0.0)
            n += 1
        out[j] = won / trials
    return i, out


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    n = len(PF_ORDER)
    eq = [[0.5] * n for _ in range(n)]
    with Pool() as pool:
        for i, out in pool.imap_unordered(row, [(i, trials) for i in range(n)]):
            for j, v in out.items():
                eq[i][j] = v
                eq[j][i] = 1.0 - v
    # compatible-combo counts: expected number of combos of class j left when we hold class i
    compat = [[0.0] * n for _ in range(n)]
    for i, a_cls in enumerate(PF_ORDER):
        for j, b_cls in enumerate(PF_ORDER):
            tot = 0
            for a in CLASS_COMBOS[a_cls]:
                tot += sum(1 for b in CLASS_COMBOS[b_cls] if a[0] not in b and a[1] not in b)
            compat[i][j] = tot / len(CLASS_COMBOS[a_cls])
    with open(OUT, 'w') as f:
        json.dump({'classes': PF_ORDER, 'trials': trials,
                   'equity': [[round(v, 4) for v in r] for r in eq],
                   'compat': [[round(v, 3) for v in r] for r in compat]}, f, separators=(',', ':'))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
