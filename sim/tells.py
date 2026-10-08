'''
Timing tells and tilt, learned per player from public information only.

TimingModel
    Every postflop action with a recorded think time is kept. Times are compared to
    the player's own normal speed for that kind of action (z-score of log time).
    When the player shows down, the strength of their hand at each of their actions
    is known, so the model learns whether fast/slow actions meant strong/weak hands
    (a correlation per action kind). Until enough showdowns are seen, it says nothing.

TiltModel
    Records the player's VPIP and results in the hands after a big loss compared with
    their normal VPIP. `tilted_now()` is true for the next few hands after a big loss
    when they have a history of loosening up after one.
'''
import math

from .engine import PREFLOP, FOLD, CHECK, CALL, BET, RAISE

AGGRO = (BET, RAISE)
PASSIVE = (CALL, CHECK)
MIN_SHOWDOWN_SAMPLES = 8


def _kind_class(kind):
    return 'aggro' if kind in AGGRO else ('passive' if kind in PASSIVE else 'fold')


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sxy / (sx * sy) if sx > 0 and sy > 0 else 0.0


class TimingModel:

    def __init__(self):
        self.times = {'aggro': [], 'passive': [], 'fold': []}   # log think times
        self.pairs = {'aggro': [], 'passive': []}               # (z, hand strength) from showdowns

    def to_dict(self):
        return {'times': self.times, 'pairs': self.pairs}

    @classmethod
    def from_dict(cls, d):
        m = cls()
        m.times.update({k: list(v) for k, v in d.get('times', {}).items()})
        m.pairs.update({k: [tuple(p) for p in v] for k, v in d.get('pairs', {}).items()})
        return m

    def observe(self, kind, think_ms):
        if think_ms is None or think_ms <= 0:
            return
        lst = self.times[_kind_class(kind)]
        lst.append(math.log(think_ms))
        del lst[:-400]

    def z(self, kind, think_ms):
        '''How unusually slow (+) or fast (-) this action was for this player.'''
        lst = self.times.get(_kind_class(kind), [])
        if think_ms is None or len(lst) < 10:
            return 0.0
        m = sum(lst) / len(lst)
        sd = math.sqrt(sum((x - m) ** 2 for x in lst) / len(lst)) or 1.0
        return max(-3.0, min(3.0, (math.log(max(think_ms, 1.0)) - m) / sd))

    def learn(self, kind, think_ms, strength):
        c = _kind_class(kind)
        if c in self.pairs and think_ms:
            self.pairs[c].append((self.z(kind, think_ms), strength))
            del self.pairs[c][:-300]

    def tell(self, kind):
        '''(correlation of slowness with strength, samples) for this kind of action.'''
        pairs = self.pairs.get(_kind_class(kind), [])
        if len(pairs) < MIN_SHOWDOWN_SAMPLES:
            return 0.0, len(pairs)
        return _corr([p[0] for p in pairs], [p[1] for p in pairs]), len(pairs)


class TiltModel:
    BIG_LOSS_BB = 30
    WINDOW = 10

    def __init__(self):
        self.since_loss = None       # hands since the last big loss (None = none yet)
        self.after = [0, 0]          # [hands, voluntary] in windows after big losses
        self.after_net = 0.0         # bb won in those windows
        self.normal = [0, 0]         # [hands, voluntary] otherwise
        self.big_losses = 0

    def to_dict(self):
        return dict(since_loss=self.since_loss, after=self.after, after_net=self.after_net,
                    normal=self.normal, big_losses=self.big_losses)

    @classmethod
    def from_dict(cls, d):
        m = cls()
        for k, v in d.items():
            setattr(m, k, v)
        m.since_loss = None          # a new session starts calm
        return m

    def update(self, vpip, net_bb):
        in_window = self.since_loss is not None and self.since_loss < self.WINDOW
        bucket = self.after if in_window else self.normal
        bucket[0] += 1
        bucket[1] += int(vpip)
        if in_window:
            self.after_net += net_bb
        if self.since_loss is not None:
            self.since_loss += 1
        if net_bb <= -self.BIG_LOSS_BB:
            self.big_losses += 1
            self.since_loss = 0

    def vpip_after(self):
        return self.after[1] / self.after[0] if self.after[0] else float('nan')

    def vpip_normal(self):
        return self.normal[1] / self.normal[0] if self.normal[0] else float('nan')

    def effect(self):
        '''How much looser they play after a big loss (0.25 = 25% more hands), 0 if unknown.'''
        if self.after[0] < 8 or self.normal[0] < 20:
            return 0.0
        base = max(0.05, self.vpip_normal())
        return max(0.0, self.vpip_after() / base - 1.0)

    def tilted_now(self):
        return (self.since_loss is not None and self.since_loss < self.WINDOW and self.effect() > 0.15)


def street_strength(hole, board):
    from .strength import postflop_strength
    return postflop_strength(list(hole), list(board))


def update_from_hand(models, h):
    '''Feed one finished hand into {name: (TimingModel, TiltModel)}.'''
    board_at = {'flop': 3, 'turn': 4, 'river': 5}
    for seat, name in enumerate(h.names):
        tm, tilt = models.setdefault(name, (TimingModel(), TiltModel()))
        acts = [a for a in h.actions if a.seat == seat]
        for a in acts:
            if a.street != PREFLOP and a.kind != FOLD:
                tm.observe(a.kind, a.think_ms)
        if seat in h.showdown:                       # cards were shown: learn what the timing meant
            for a in acts:
                if a.street != PREFLOP and a.kind in AGGRO + PASSIVE and a.think_ms:
                    tm.learn(a.kind, a.think_ms, street_strength(h.hole[seat], h.board[:board_at[a.street]]))
        vpip = any(a.street == PREFLOP and a.kind in (CALL, RAISE) for a in acts)
        tilt.update(vpip, h.winnings[seat] / h.big_blind)
