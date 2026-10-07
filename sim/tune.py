'''
Tune a bot's Params for win rate (rather than for matching stats).

Every candidate in a generation plays the same duplicate deals (common random
numbers), so candidates are compared on a paired basis and the noise in the
comparison is far lower than the noise in each win rate. The incumbent is
re-evaluated each generation on fresh deals, so a lucky score can't stick.

    python -m sim.tune --start AnteTAG --generations 15
'''
import argparse
import os
import random
from dataclasses import asdict
from multiprocessing import Pool

from .bots import PRESETS, Params
from .calibrate import BOUNDS as FIT_BOUNDS, TABLE
from .match import run_match

BOUNDS = dict(FIT_BOUNDS, open_size=(2.0, 4.5), pos_spread=(0.0, 3.0), iso=(1.0, 3.0),
              iso_per_limper=(0.5, 2.5))
BOUNDS.pop('limp')   # limping stays off: raise-or-fold

# opponents for tuning: two soft tables and one table of regulars, so the result
# can't overfit to fish
TUNE_TABLES = {
    'fish': ['Station', 'Nervous', 'Scared', 'Maniac', 'LAG', 'Nit'],
    'passive': ['Nervous', 'Scared', 'Terrified', 'Station', 'Nit', 'TAG'],
    'regs': ['TAG', 'LAG', 'TAG', 'LAG', 'Nit', 'Maniac'],
}


def _job(args):
    cand, table, deals, seed = args
    lineup = [('CAND', 'Hero')] + [(k, '%s%d' % (k, i)) for i, k in enumerate(TUNE_TABLES[table])]
    res = run_match(lineup, deals, seed=seed, params={'CAND': cand}, **TABLE)
    return 100 * sum(res.blocks['Hero']) / len(res.blocks['Hero'])


def _mutate(p, rng, scale):
    d = asdict(p)
    for k, (lo, hi) in BOUNDS.items():
        if rng.random() < 0.4:
            d[k] = min(hi, max(lo, d[k] + rng.gauss(0, scale * (hi - lo))))
    return Params(**d)


def evaluate(cands, deals, seed, pool):
    jobs = [(c, t, deals, seed + k) for c in cands for k, t in enumerate(TUNE_TABLES)]
    scores = pool.map(_job, jobs, chunksize=1)
    nt = len(TUNE_TABLES)
    return [sum(scores[i * nt:(i + 1) * nt]) / nt for i in range(len(cands))]


def tune(start, generations=15, children=7, deals=2000, seed=0, procs=None, log=print):
    rng = random.Random(seed)
    best = start
    history = []
    with Pool(procs or os.cpu_count()) as pool:
        for g in range(generations):
            scale = 0.12 * (1 - g / generations) + 0.03
            cands = [best] + [_mutate(best, rng, scale) for _ in range(children)]
            scores = evaluate(cands, deals, seed=1000 * (g + 1) + seed, pool=pool)
            k = max(range(len(cands)), key=lambda i: scores[i])
            log('gen %2d: incumbent %+6.1f  best %+6.1f bb/100 (mean over tables)' % (g, scores[0], scores[k]))
            history.append((scores[0], scores[k]))
            best = cands[k]
    return best, history


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--start', default='AnteTAG')
    ap.add_argument('--generations', type=int, default=15)
    ap.add_argument('--deals', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args(argv)
    best, _ = tune(PRESETS[a.start], a.generations, deals=a.deals, seed=a.seed)
    print(repr(best))


if __name__ == '__main__':
    main()
