'''
Match runner with duplicate dealing.

In duplicate mode every deal is replayed once per seat rotation, so each bot
gets every seat's cards exactly once. Card luck mostly cancels, which cuts
the hands needed to measure a win-rate difference by an order of magnitude.

Results are in bb/100 with 95% confidence intervals computed over deal blocks.
'''
import math
from dataclasses import dataclass

from .bots import make_bot
from .engine import Table
from .stats import StatsTracker


@dataclass
class MatchResult:
    names: list
    blocks: dict          # name -> list of bb/hand averaged over one deal block
    observer: StatsTracker
    hands: int

    def bb100(self, name, lo=0, hi=None):
        xs = self.blocks[name][lo:hi]
        return 100 * sum(xs) / len(xs)

    def ci95(self, name, lo=0, hi=None):
        return 1.96 * 100 * _se(self.blocks[name][lo:hi])


def _se(xs):
    n = len(xs)
    if n < 2:
        return float('nan')
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var / n)


def paired_diff(a, b, lo=0, hi=None):
    '''bb/100 difference between two block series played on the same deals, with 95% CI.'''
    d = [x - y for x, y in zip(a[lo:hi], b[lo:hi])]
    return 100 * sum(d) / len(d), 1.96 * 100 * _se(d)


def run_match(lineup, n_deals, seed=0, duplicate=True, stack_bb=100, big_blind=2, allin_ev=True):
    '''
    PARAMETERS:
        lineup: list of (kind, name) pairs, kind is 'Exploit' or a PRESETS key
        n_deals: number of distinct deals (hands played = n_deals * seats if duplicate)
        seed: base seed; the same seed gives the same deals for any lineup of the same size
        allin_ev: score hands where players were all-in before the river by equity
                  instead of the actual runout (unbiased, much lower variance)

    RETURN: MatchResult
    '''
    bots = [make_bot(kind, name, seed=seed * 1000 + i) for i, (kind, name) in enumerate(lineup)]
    n = len(bots)
    table = Table(big_blind=big_blind, stack_bb=stack_bb)
    observer = StatsTracker()
    blocks = {b.name: [] for b in bots}
    rotations = n if duplicate else 1
    hand_id = 0
    for d in range(n_deals):
        deck_seed = seed * 10_000_000 + d
        net = [0.0] * n
        for r in range(rotations):
            rot = r if duplicate else d % n
            order = [bots[(j + rot) % n] for j in range(n)]
            h = table.play_hand(order, deck_seed, hand_id)
            hand_id += 1
            observer.update(h)
            result = h.ev_winnings if (allin_ev and h.ev_winnings) else h.winnings
            for j in range(n):
                net[(j + rot) % n] += result[j] / big_blind
        for i, b in enumerate(bots):
            blocks[b.name].append(net[i] / rotations)
    return MatchResult([b.name for b in bots], blocks, observer, hand_id)
