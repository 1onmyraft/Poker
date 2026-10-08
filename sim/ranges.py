'''
Hand ranges with card removal, and equity against them.

A range is a weight for each of the 1326 two-card combos. Combos that use a
card we can see (our hole cards, the board) are impossible and get weight 0,
so e.g. with three aces on the board and an ace in our hand, an opponent's
range contains no aces at all.

- `Range`: weights over combos; build from preflop actions, narrow on bets.
- `equity(hole, board, ranges)`: Monte Carlo equity against one or more ranges,
  dealing each opponent a combo from their range without card conflicts.
- `RangeTracker`: rebuilds every opponent's range from the hand's public actions.
'''
import bisect
import random
from itertools import combinations

from .cards import DECK, evaluate, hand_code, PF_PERCENTILE
from .engine import PREFLOP, CHECK, CALL, BET, RAISE

COMBOS = [tuple(c) for c in combinations(DECK, 2)]          # 1326
COMBO_INDEX = {c: i for i, c in enumerate(COMBOS)}
COMBO_INDEX.update({(b, a): i for (a, b), i in list(COMBO_INDEX.items())})
COMBO_CLASS = [hand_code(list(c)) for c in COMBOS]
# 0 = best starting hand (AA), 1 = worst (72o), by the same ordering the bots use
COMBO_PCT = [PF_PERCENTILE[k] for k in COMBO_CLASS]


class Range:
    '''Weights over the 1326 combos.'''

    __slots__ = ('w',)

    def __init__(self, weights=None):
        self.w = list(weights) if weights is not None else [1.0] * len(COMBOS)

    @classmethod
    def band(cls, lo, hi, floor=0.02):
        '''Combos whose starting-hand percentile is in [lo, hi] (0 = AA), a small floor elsewhere.'''
        return cls([1.0 if lo <= p <= hi else floor for p in COMBO_PCT])

    def copy(self):
        return Range(self.w)

    def remove(self, dead):
        '''Card removal: zero every combo containing a dead card.'''
        dead = set(dead)
        for i, (a, b) in enumerate(COMBOS):
            if a in dead or b in dead:
                self.w[i] = 0.0
        return self

    def total(self):
        return sum(self.w)

    def live(self, dead=()):
        '''(combos, cumulative weights) of combos possible given dead cards, for sampling.'''
        dead = set(dead)
        combos, cum, acc = [], [], 0.0
        for c, w in zip(COMBOS, self.w):
            if w > 0 and c[0] not in dead and c[1] not in dead:
                acc += w
                combos.append(c)
                cum.append(acc)
        return combos, cum

    def top_classes(self, n=8):
        '''Most likely starting-hand classes, for display/debugging.'''
        agg = {}
        for k, w in zip(COMBO_CLASS, self.w):
            agg[k] = agg.get(k, 0.0) + w
        tot = sum(agg.values()) or 1.0
        return [(k, v / tot) for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:n]]


def equity(hole, board, ranges, samples=300, rng=None):
    '''
    Our equity (ties split) against opponents holding hands from `ranges`
    (one Range per opponent still in the hand), by Monte Carlo.
    '''
    rng = rng or random.Random(0)
    dead = set(hole) | set(board)
    lives = []
    for r in ranges:
        combos, cum = r.live(dead)
        if not combos:                      # impossible range: treat as random hand
            combos, cum = Range().live(dead)
        lives.append((combos, cum))
    deck = [c for c in DECK if c not in dead]
    need = 5 - len(board)
    won = 0.0
    done = 0
    tries = 0
    while done < samples and tries < samples * 20:
        tries += 1
        used = set()
        opp = []
        ok = True
        for combos, cum in lives:
            for _ in range(10):
                c = combos[bisect.bisect_left(cum, rng.random() * cum[-1])]
                if c[0] not in used and c[1] not in used:
                    break
            else:
                ok = False
                break
            used.update(c)
            opp.append(c)
        if not ok:
            continue
        rest = [c for c in deck if c not in used]
        runout = rng.sample(rest, need) if need else []
        full = list(board) + runout
        mine = evaluate(list(hole) + full)
        best = max(evaluate(list(c) + full) for c in opp)
        if mine > best:
            won += 1
        elif mine == best:
            ties = sum(1 for c in opp if evaluate(list(c) + full) == mine)
            won += 1.0 / (ties + 1)
        done += 1
    return won / max(1, done)


# ----------------------------------------------------------------------------- tracking

_STRENGTH = {}          # board -> {combo index: strength}, shared by every tracker and bot


def _combo_strength(i, board):
    '''How strong combo i is on this board, 0..1 (made hand class plus draws), cached per board.'''
    key = tuple(board)
    cache = _STRENGTH.get(key)
    if cache is None:
        if len(_STRENGTH) > 256:
            _STRENGTH.clear()
        cache = _STRENGTH[key] = {}
    v = cache.get(i)
    if v is None:
        from .strength import postflop_strength
        v = cache[i] = postflop_strength(list(COMBOS[i]), list(board))
    return v


class RangeTracker:
    '''
    Rebuilds each opponent's range from public information only:

    preflop  - opening raise: their raising range (observed PFR, default by position)
               call         : the band below their raising range down to their VPIP
               3-bet+       : the top of their range
               limp / check : weaker, wider ranges
    postflop - bets and raises shift weight to strong hands and draws; calls to
               medium hands; checks slightly away from the strongest hands.
    Card removal is applied for every card we can see.
    '''

    POSITION_OPEN = {'UTG': 0.14, 'UTG+1': 0.15, 'UTG+2': 0.16, 'MP': 0.18, 'HJ': 0.22, 'CO': 0.28,
                     'BTN': 0.40, 'SB': 0.35, 'BB': 0.30}

    def __init__(self, stats=None):
        self.stats = stats          # optional StatsTracker for observed tendencies
        self._cache = {}

    def _rates(self, name):
        p = self.stats.players.get(name) if self.stats else None
        if not p or p.hands < 15:
            return None
        return p.rate('vpip', k=20), p.rate('pfr', k=20), p.rate('three_bet', k=20)

    def preflop_range(self, st, seat):
        acts = [a for a in st.history if a.street == PREFLOP]
        name = st.names[seat]
        pos = st.positions[seat]
        rates = self._rates(name)
        open_w = self.POSITION_OPEN.get(pos, 0.2)
        vpip, pfr, tb = (rates if rates else (open_w + 0.1, open_w, 0.06))
        raises_before = 0
        last = None
        for a in acts:
            if a.seat == seat:
                last = (a.kind, raises_before)
            if a.kind == RAISE:
                raises_before += 1
        if last is None:                                  # hasn't acted preflop (e.g. a blind walk)
            return Range()
        kind, rb = last
        if kind == RAISE and rb == 0:                     # open raise
            return Range.band(0.0, max(0.03, pfr))
        if kind == RAISE:                                 # 3-bet or more: the top of their range
            return Range.band(0.0, max(0.02, tb if rb == 1 else tb * 0.5))
        if kind == CALL and rb == 0:                      # limp
            return Range.band(max(0.0, pfr * 0.5), min(1.0, max(vpip, pfr + 0.15)), floor=0.05)
        if kind == CALL:                                  # flat a raise
            return Range.band(min(pfr, 0.06), min(1.0, max(vpip, pfr + 0.08)), floor=0.03)
        return Range()                                    # checked the big blind: anything

    def range_for(self, st, seat, dead):
        """Opponent's current range given everything public this hand, with card removal.

        Kept per hand and updated incrementally: only actions since the last call are applied."""
        key = (st.hand_id, st.names[seat], st.positions[seat], seat)
        done, r = self._cache.get(key, (None, None))
        if r is None:
            r = self.preflop_range(st, seat)
            done = sum(1 for a in st.history if a.street == PREFLOP)
            if len(self._cache) > 200:
                self._cache.clear()
        board_at = {'flop': 3, 'turn': 4, 'river': 5}
        for a in st.history[done:]:
            if a.street == PREFLOP or a.seat != seat:
                continue
            board = st.board[:board_at[a.street]]
            r.remove(board)
            self._narrow(r, a.kind, board, a.to_call, a.pot)
        self._cache[key] = (len(st.history), r)
        return r.copy().remove(list(st.board) + list(dead))

    @staticmethod
    def _narrow(r, kind, board, to_call, pot):
        if kind not in (BET, RAISE, CALL, CHECK):
            return
        for i, c in enumerate(COMBOS):
            if r.w[i] <= 0 or c[0] in board or c[1] in board:
                continue
            s = _combo_strength(i, board)
            if kind in (BET, RAISE):
                f = 0.15 + 0.85 * s ** 1.5 + (0.2 if 0.25 < s < 0.5 else 0.0)   # value + some draws/bluffs
            elif kind == CALL:
                f = 0.3 + 0.7 * min(1.0, s * 1.6) * (1.0 if s < 0.9 else 0.8)  # medium hands, few nuts
            else:
                f = 1.0 if s < 0.85 else 0.55                                  # checks: fewer monsters
            r.w[i] *= f
