'''
Fit bot parameters so a bot reproduces the tendencies seen in a hand history.

The distance between simulated and observed stats is measured in standard
errors of the *observed* sample, so stats seen only a handful of times barely
constrain the fit. Search is a simple (1+lambda) evolution strategy run in
parallel; the incumbent is re-evaluated every generation so a lucky noisy
evaluation can't stick.

    python -m sim.calibrate HISTORY.txt
'''
import argparse
import math
import os
import random
from dataclasses import asdict, replace
from multiprocessing import Pool

from .bots import PRESETS, Params
from .handhistory import parse_file, replay
from .match import run_match
from .stats import StatsTracker, STAT_INFO

FIT_KEYS = ['vpip', 'pfr', 'limp', 'three_bet', 'fold_3bet', 'fold_steal', 'cbet', 'fold_cbet',
            'fvb_small', 'fvb_big', 'afq', 'wtsd', 'wsd']

# search bounds per parameter
BOUNDS = {
    'open': (0.03, 0.70), 'steal_mult': (1.0, 2.5), 'limp': (0.0, 0.8), 'call_open': (0.01, 0.6),
    'bb_defend': (1.0, 2.5), 'threebet': (0.003, 0.30), 'call_3bet': (0.005, 0.5),
    'fourbet': (0.003, 0.15), 'value': (0.40, 0.95), 'bluff': (0.0, 0.6), 'cbet': (0.05, 1.0),
    'semibluff': (0.0, 1.0), 'call_margin': (-0.2, 0.35), 'fear': (0.0, 1.5),
    'raise_value': (0.6, 0.98), 'raise_bluff': (0.0, 0.25), 'bet_size': (0.33, 1.0),
}

# the 7-max ante structure of the sample histories, in cents
TABLE = dict(big_blind=10, small_blind=10, ante=10, rake=0.05, rake_cap=150, stack_range=(40, 120))


def observed_stats(path, hero=True):
    '''Stats for Hero and for all other players pooled (names are anonymous per hand).'''
    tr = StatsTracker()
    for ph in parse_file(path):
        h, _ = replay(ph)
        h.names = ['Hero' if x == ph.hero else 'Pool' for x in h.names]
        tr.update(h)
    return tr.get('Hero'), tr.get('Pool')


def target_from(p):
    '''{key: (rate, standard error)} from a PlayerStats.'''
    out = {}
    for k in FIT_KEYS:
        st = p.stats[k]
        if st.opp >= 5:
            r = st.count / st.opp
            out[k] = (r, max(0.02, math.sqrt(max(r * (1 - r), 0.05) / st.opp)))
    return out


def distance(sim, target):
    return sum(((sim.rate(k, shrink=False) - r) / se) ** 2
               for k, (r, se) in target.items() if sim.stats[k].opp)


def _evaluate(args):
    params_by_kind, lineup, focus, deals, seed = args
    res = run_match(lineup, deals, seed=seed, duplicate=False, params=params_by_kind, **TABLE)
    return {name: res.observer.get(name) for name in focus}


def _mutate(p, rng, scale):
    d = asdict(p)
    for k, (lo, hi) in BOUNDS.items():
        if rng.random() < 0.5:
            d[k] = min(hi, max(lo, d[k] + rng.gauss(0, scale * (hi - lo))))
    return Params(**d)


def fit(target, role, others, start, generations=14, children=8, deals=400, seed=0, procs=None,
        log=print):
    '''
    Fit Params for `role` ('pool' = all six opponents, or 'hero' = one seat) so its stats
    match `target`. `others` are the fixed Params for the other role.
    '''
    rng = random.Random(seed)
    procs = procs or os.cpu_count()

    def job(cand, s):
        if role == 'pool':
            params = {'P': cand, 'H': others}
            lineup = [('H', 'Hero')] + [('P', 'Pool%d' % i) for i in range(6)]
            focus = ['Pool%d' % i for i in range(6)]
        else:
            params = {'P': others, 'H': cand}
            lineup = [('H', 'Hero')] + [('P', 'Pool%d' % i) for i in range(6)]
            focus = ['Hero']
        return (params, lineup, focus, deals, s)

    def merged_distance(stats_list):
        merged = StatsTracker().get('m')
        for p in stats_list:
            for k in FIT_KEYS:
                merged.stats[k].count += p.stats[k].count
                merged.stats[k].opp += p.stats[k].opp
        return distance(merged, target), merged

    best, best_d, best_stats = start, None, None
    with Pool(procs) as pool:
        for g in range(generations):
            scale = 0.15 * (1 - g / generations) + 0.03
            cands = [best] + [_mutate(best, rng, scale) for _ in range(children)]
            seeds = [rng.randrange(10 ** 6) for _ in cands]
            outs = pool.map(_evaluate, [job(c, s) for c, s in zip(cands, seeds)])
            scored = [merged_distance(list(o.values())) + (c,) for o, c in zip(outs, cands)]
            d, stats, c = min(scored, key=lambda x: x[0])
            best, best_d, best_stats = c, d, stats
            log('  %s gen %2d: distance %.1f' % (role, g, d))
    return best, best_d, best_stats


def closest_preset(target):
    '''Cheap starting point: the preset whose name-level style best matches VPIP/PFR/AFq.'''
    vp, pf, af = (target.get(k, (0.25, 0))[0] for k in ('vpip', 'pfr', 'afq'))
    style = {'TAG': (0.20, 0.17, 0.32), 'LAG': (0.25, 0.18, 0.42), 'Nit': (0.08, 0.08, 0.17),
             'Station': (0.44, 0.07, 0.09), 'Maniac': (0.58, 0.48, 0.61),
             'Nervous': (0.19, 0.10, 0.14), 'Scared': (0.19, 0.07, 0.08),
             'Terrified': (0.18, 0.04, 0.04)}
    return min(style, key=lambda k: (style[k][0] - vp) ** 2 + (style[k][1] - pf) ** 2 + (style[k][2] - af) ** 2)


def calibrate(path, rounds=2, log=print, **kw):
    hero_obs, pool_obs = observed_stats(path)
    t_hero, t_pool = target_from(hero_obs), target_from(pool_obs)
    pool_p = PRESETS[closest_preset(t_pool)]
    hero_p = PRESETS[closest_preset(t_hero)]
    log('start: pool=%s hero=%s' % (closest_preset(t_pool), closest_preset(t_hero)))
    pool_stats = hero_stats = None
    for r in range(rounds):
        pool_p, d_pool, pool_stats = fit(t_pool, 'pool', hero_p, pool_p, seed=10 * r + 1, log=log, **kw)
        hero_p, d_hero, hero_stats = fit(t_hero, 'hero', pool_p, hero_p, seed=10 * r + 2, log=log, **kw)
    return {'pool': (pool_p, t_pool, pool_stats), 'hero': (hero_p, t_hero, hero_stats)}


def fit_table(target, sim):
    rows = ['| Stat | Observed | Fitted bot |', '|---|---:|---:|']
    for k, (r, se) in target.items():
        rows.append('| %s | %.0f%% ± %.0f | %.0f%% |' % (STAT_INFO[k][0], 100 * r, 196 * se,
                                                        100 * sim.rate(k, shrink=False)))
    return '\n'.join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('history')
    a = ap.parse_args(argv)
    out = calibrate(a.history)
    for role, (p, t, st) in out.items():
        print('\n## %s\n' % role)
        print(fit_table(t, st))
        print('\n' + repr(p))


if __name__ == '__main__':
    main()


def _versus_job(args):
    hero_kind, params, deals, seed = args
    lineup = [(hero_kind, 'Hero')] + [('PoolClone', 'Pool%d' % i) for i in range(6)]
    res = run_match(lineup, deals, seed=seed, params=params, **TABLE)
    return hero_kind, res.blocks['Hero'], res.hands


def versus(pool_p, hero_p, heroes, deals=20000, seed=42, procs=None):
    '''Each hero kind vs six PoolClones, same duplicate deals for every hero.'''
    params = {'PoolClone': pool_p, 'HeroClone': hero_p}
    with Pool(procs or os.cpu_count()) as pool:
        out = pool.map(_versus_job, [(k, params, deals, seed) for k in heroes], chunksize=1)
    return {k: (blocks, hands) for k, blocks, hands in out}
