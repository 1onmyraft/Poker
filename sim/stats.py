'''
Player tendency stats (HUD-style) computed from hand histories.

Every percentage stat is a (count, opportunities) pair, so you can tell 3/4
from 300/400. `rate()` shrinks small samples toward a population prior:

    estimate = (count + prior * k) / (opportunities + k)

Only public information is used (actions and showdown results), so bots may
safely keep their own tracker to model opponents.
'''
from collections import defaultdict
from dataclasses import dataclass

from .engine import PREFLOP, FLOP, FOLD, CHECK, CALL, BET, RAISE

STEAL_POSITIONS = ('CO', 'BTN', 'SB')
BLIND_POSITIONS = ('SB', 'BB')

# key: (label, population prior, description)
STAT_INFO = {
    'vpip':      ('VPIP',    0.25, 'voluntarily put chips in preflop'),
    'pfr':       ('PFR',     0.18, 'raised preflop'),
    'limp':      ('Limp',    0.10, 'called the big blind when first in or behind limpers'),
    'three_bet': ('3Bet',    0.07, 're-raised a single raise preflop'),
    'fold_3bet': ('F3B',     0.55, 'opened, then folded to a 3-bet'),
    'steal':     ('Steal',   0.35, 'opened from CO/BTN/SB when folded to'),
    'fold_steal': ('FtS',    0.65, 'folded a blind to a steal'),
    'cbet':      ('CBet',    0.60, 'preflop raiser bet the flop when checked to'),
    'fold_cbet': ('FCB',     0.45, 'folded to a flop c-bet'),
    'fvb':       ('FvB',     0.45, 'folded when facing a postflop bet/raise'),
    'fvb_small': ('FvB<½',   0.40, 'folded facing a postflop bet under half pot'),
    'fvb_big':   ('FvB≥½',   0.50, 'folded facing a postflop bet of half pot or more'),
    'afq':       ('AFq',     0.40, 'share of postflop actions that were bets/raises'),
    'check_raise': ('XR',    0.08, 'check-raised after checking'),
    'wtsd':      ('WTSD',    0.28, 'went to showdown after seeing the flop'),
    'wsd':       ('W$SD',    0.50, 'won money at showdown'),
    'wwsf':      ('WWSF',    0.45, 'won money after seeing the flop'),
}


@dataclass
class Stat:
    count: int = 0
    opp: int = 0

    def add(self, hit):
        self.opp += 1
        self.count += bool(hit)

    def raw(self):
        return self.count / self.opp if self.opp else float('nan')

    def shrunk(self, prior, k):
        return (self.count + prior * k) / (self.opp + k)


class PlayerStats:

    def __init__(self, name):
        self.name = name
        self.hands = 0
        self.net = 0.0           # in big blinds
        self.stats = defaultdict(Stat)
        self.post_aggr = 0       # postflop bets + raises
        self.post_calls = 0

    def rate(self, key, k=20, shrink=True):
        st = self.stats[key]
        if not shrink:
            return st.raw()
        return st.shrunk(STAT_INFO[key][1], k)

    def n(self, key):
        return self.stats[key].opp

    def af(self):
        '''Aggression factor (bets+raises)/calls, lightly smoothed.'''
        return (self.post_aggr + 1) / (self.post_calls + 1)

    def confidence(self, key, k=30):
        '''0 -> no data, 1 -> lots of data; for blending exploits in gradually.'''
        n = self.stats[key].opp
        return n / (n + k)


class StatsTracker:

    def __init__(self):
        self.players = {}

    def get(self, name):
        if name not in self.players:
            self.players[name] = PlayerStats(name)
        return self.players[name]

    def update(self, h):
        ps = [self.get(name) for name in h.names]
        for i, p in enumerate(ps):
            p.hands += 1
            p.net += h.winnings[i] / h.big_blind

        self._preflop(h, ps)
        pfa = self._preflop_aggressor(h)
        for street in (FLOP, 'turn', 'river'):
            self._postflop_street(h, ps, street, pfa)

        saw_flop = set(h.saw_street.get(FLOP, []))
        if FLOP in h.saw_street and len(saw_flop) > 1:
            for i in saw_flop:
                went = i in h.showdown
                ps[i].stats['wtsd'].add(went)
                ps[i].stats['wwsf'].add(h.winnings[i] > 0)
                if went:
                    ps[i].stats['wsd'].add(h.winnings[i] > 0)

    @staticmethod
    def _preflop_aggressor(h):
        agg = None
        for e in h.actions:
            if e.street == PREFLOP and e.kind == RAISE:
                agg = e.seat
        return agg

    def _preflop(self, h, ps):
        raises = 1           # the big blind
        opener = None
        voluntary = set()
        callers_after_open = 0
        seen = defaultdict(set)   # seat -> which opportunity types already counted
        vpip, pfr = set(), set()

        for e in (a for a in h.actions if a.street == PREFLOP):
            i, pos, st = e.seat, h.positions[e.seat], ps[e.seat].stats
            if e.kind in (CALL, RAISE):
                vpip.add(i)
            if e.kind == RAISE:
                pfr.add(i)

            if raises == 1 and pos != 'BB' and 'open' not in seen[i]:
                seen[i].add('open')
                st['limp'].add(e.kind == CALL)
                if not voluntary and pos in STEAL_POSITIONS:
                    st['steal'].add(e.kind == RAISE)
            if raises == 2 and i != opener and 'three_bet' not in seen[i]:
                seen[i].add('three_bet')
                st['three_bet'].add(e.kind == RAISE)
                if (pos in BLIND_POSITIONS and i not in voluntary and callers_after_open == 0
                        and h.positions[opener] in STEAL_POSITIONS and h.positions[opener] != pos):
                    st['fold_steal'].add(e.kind == FOLD)
            if raises == 3 and i == opener and 'fold_3bet' not in seen[i]:
                seen[i].add('fold_3bet')
                st['fold_3bet'].add(e.kind == FOLD)

            if e.kind == RAISE:
                raises += 1
                if raises == 2:
                    opener = i
            elif e.kind == CALL and raises == 2:
                callers_after_open += 1
            if e.kind in (CALL, RAISE):
                voluntary.add(i)

        for i, p in enumerate(ps):
            p.stats['vpip'].add(i in vpip)
            p.stats['pfr'].add(i in pfr)

    def _postflop_street(self, h, ps, street, pfa):
        acts = [a for a in h.actions if a.street == street]
        if not acts:
            return
        bet_open = False
        first_bettor = None
        bet_count = 0
        faced = set()
        checked = set()
        cbet_counted = False
        for e in acts:
            i, st = e.seat, ps[e.seat].stats
            if e.kind in (BET, RAISE):
                ps[i].post_aggr += 1
            elif e.kind == CALL:
                ps[i].post_calls += 1
            st['afq'].add(e.kind in (BET, RAISE))

            if street == FLOP and i == pfa and not bet_open and not cbet_counted:
                cbet_counted = True
                st['cbet'].add(e.kind == BET)

            if e.to_call > 0 and i not in faced:
                faced.add(i)
                st['fvb'].add(e.kind == FOLD)
                pot_before_bet = max(1, e.pot - e.to_call)
                key = 'fvb_small' if e.to_call < 0.5 * pot_before_bet else 'fvb_big'
                st[key].add(e.kind == FOLD)
                if street == FLOP and first_bettor is not None and first_bettor == pfa and bet_count == 1:
                    st['fold_cbet'].add(e.kind == FOLD)
                if i in checked:
                    st['check_raise'].add(e.kind == RAISE)

            if e.kind == CHECK:
                checked.add(i)
            if e.kind in (BET, RAISE):
                if not bet_open:
                    first_bettor = i
                bet_open = True
                bet_count += 1

    def table(self, names=None, keys=None, k=0):
        '''Plain-text stats table. k=0 shows raw rates; k>0 shows shrunk estimates.'''
        keys = keys or ['vpip', 'pfr', 'three_bet', 'steal', 'fold_steal', 'cbet', 'fold_cbet',
                        'fvb', 'afq', 'wtsd', 'wsd']
        names = names or list(self.players)
        head = '%-12s %7s ' % ('player', 'hands') + ' '.join('%6s' % STAT_INFO[key][0] for key in keys) + '  %5s' % 'AF'
        lines = [head, '-' * len(head)]
        for name in names:
            p = self.players[name]
            vals = []
            for key in keys:
                r = p.rate(key, k=k, shrink=k > 0)
                vals.append('%6s' % ('-' if r != r else '%.0f' % (100 * r)))
            lines.append('%-12s %7d ' % (name, p.hands) + ' '.join(vals) + '  %5.2f' % p.af())
        return '\n'.join(lines)
