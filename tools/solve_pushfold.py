'''
Solve short-stack push/fold equilibria for every table size (2-9) and both game
structures, and write resources/pushfold.json for the bots.

Model (the standard "Nash push/fold" setup, extended to antes and n players):
- everyone has the same effective stack S (in big blinds); the first player to enter
  either shoves all-in or folds; later players either call the shove or fold
- equities come from the 169x169 table (tools/build_preflop_equity.py), weighted by
  how many combos of each hand remain given ours (card removal)
- any subset of the later players may call (each independently, with card removal
  from our hand); equity against several callers is the product of heads-up equities
Solved by fictitious play (averaged best responses), which converges for these games.

    python tools/solve_pushfold.py
'''
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim.engine import position_names       # noqa: E402

STRUCTS = {'ante': dict(sb=1.0, bb=1.0, ante=1.0), 'classic': dict(sb=0.5, bb=1.0, ante=0.0)}
DEPTHS = list(range(2, 26))


def action_order(n):
    '''Preflop acting order as position names (first to act ... big blind).'''
    names = position_names(n)
    if n == 2:
        return ['BTN', 'BB']
    return names[3:] + names[:3]          # UTG ... CO, BTN, SB, BB


def _subsets(items):
    out = [()]
    for x in items:
        out += [o + (x,) for o in out]
    return out


def solve(n, S, st, E, C, iters=250):
    """
    Multiway-aware: every subset of later players may call. Each later player calls
    independently with their calling strategy (conditioned on our hand through card
    removal), and equity against several callers is the product of the heads-up
    equities (an independence approximation).
    """
    order = action_order(n)
    blind = {p: 0.0 for p in order}
    if n == 2:
        blind['BTN'], blind['BB'] = st['sb'], st['bb']
    else:
        blind['SB'], blind['BB'] = st['sb'], st['bb']
    a = st['ante']
    dead_all = n * a + sum(blind.values())
    H = E.shape[0]
    Csum = C.sum(1)
    CE = C * E
    push = {p: np.full(H, 0.3) for p in order[:-1]}
    call = {(q, p): np.full(H, 0.3) for i, p in enumerate(order[:-1]) for q in order[i + 1:]}

    def caller_stats(q, p, as_seen_by):
        """For each hand h of `as_seen_by`'s: P(q calls p's shove), equity of h vs q's calling range."""
        cr = call[(q, p)]
        callw = C @ cr
        return callw / Csum, np.where(callw > 0, (CE @ cr) / np.maximum(callw, 1e-12), 0.5)

    for t in range(1, iters + 1):
        new_push, new_call = {}, {}
        for i, p in enumerate(order[:-1]):
            later = order[i + 1:]
            stats = {q: caller_stats(q, p, p) for q in later}
            # shover: sum over which later players call
            ev = np.zeros(H)
            for sub in _subsets(later):
                prob = np.ones(H)
                eq = np.ones(H)
                for q in later:
                    cp, e = stats[q]
                    if q in sub:
                        prob = prob * cp
                        eq = eq * e
                    else:
                        prob = prob * (1 - cp)
                if not sub:
                    ev += prob * (dead_all - a - blind[p])
                else:
                    pot = dead_all - blind[p] - sum(blind[q] for q in sub) + (len(sub) + 1) * S
                    ev += prob * (eq * pot - S)
            new_push[p] = (ev > -(a + blind[p])).astype(float)
            # callers: q facing p's shove; players after q may overcall
            w = C * push[p][None, :]
            den = w.sum(1)
            eq_vs_p = np.where(den > 0, (w * E).sum(1) / np.maximum(den, 1e-12), 0.5)
            for j, q in enumerate(later):
                after = later[j + 1:]
                ev_c = np.zeros(H)
                for sub in _subsets(after):
                    prob = np.ones(H)
                    eq = eq_vs_p.copy()
                    for r in after:
                        cp, e = stats[r]           # r's calling range, seen from our hand's blockers
                        if r in sub:
                            prob = prob * cp
                            eq = eq * e
                        else:
                            prob = prob * (1 - cp)
                    pot = dead_all - blind[p] - blind[q] - sum(blind[r] for r in sub) + (len(sub) + 2) * S
                    ev_c += prob * (eq * pot - S)
                new_call[(q, p)] = (ev_c > -(a + blind[q])).astype(float)
        lr = 1.0 / (t + 1)
        for p in push:
            push[p] += lr * (new_push[p] - push[p])
        for k in call:
            call[k] += lr * (new_call[k] - call[k])
    return order, push, call


def pack(classes, vec):
    """169 yes/no flags (in classes order) as a hex string."""
    bits = 0
    for h in range(len(classes)):
        if vec[h] >= 0.5:
            bits |= 1 << h
    return '%x' % bits


def _job(args):
    name, n, S = args
    data = json.load(open(os.path.join(ROOT, 'resources', 'preflop_equity.json')))
    classes = data['classes']
    order, push, call = solve(n, float(S), STRUCTS[name], np.array(data['equity']), np.array(data['compat']))
    return '%s/%d/%d' % (name, n, S), {
        'push': {p: pack(classes, push[p]) for p in push},
        'call': {'%s<%s' % (q, p): pack(classes, v) for (q, p), v in call.items()},
    }


def main():
    from multiprocessing import Pool
    classes = json.load(open(os.path.join(ROOT, 'resources', 'preflop_equity.json')))['classes']
    jobs = [(name, n, S) for name in STRUCTS for n in range(9, 1, -1) for S in DEPTHS]
    out = {'classes_order': classes, 'depths': DEPTHS, 'encoding': 'hex bitmask over classes_order',
           'model': 'first-in shove/fold vs call/fold, multiway callers, fictitious play', 'charts': {}}
    with Pool() as pool:
        for key, chart in pool.imap_unordered(_job, jobs):
            out['charts'][key] = chart
    path = os.path.join(ROOT, 'resources', 'pushfold.json')
    with open(path, 'w') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=True)
    print('wrote', path, os.path.getsize(path) // 1024, 'KB,', len(out['charts']), 'charts')


if __name__ == '__main__':
    main()
