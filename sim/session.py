'''
A playable session: one human against bots, with persistent stacks.

`Session` owns the table seats, moves the button, rebuys busted players,
keeps a StatsTracker for the HUD, and (optionally) appends every hand to a
hand-history file in the 1onmyraftpoker format so you can backtest your own
play later. It has no GUI code; the view plugs in through the `human` agent
and an optional `observer`, which makes the whole thing testable headless.
'''
import os
import random
from dataclasses import dataclass, field
from datetime import datetime

from .bots import make_bot
from .engine import Table, Action, CHECK, CALL
from .handhistory import write_hand
from .stats import StatsTracker

STRUCTURES = {
    # chips are "cents": a 10-chip big blind prints as ₮0.10 in saved histories
    'ante': dict(small_blind=10, big_blind=10, ante=10, label='Ante game: 10/10 + 10 ante (like the sample)'),
    'classic': dict(small_blind=5, big_blind=10, ante=0, label='Classic: 5/10, no ante'),
}
BOT_CHOICES = ['Wizard', 'Hunter', 'AnteMax', 'Maniac', 'AnteTAG', 'Station', 'Nervous', 'Scared',
               'Terrified', 'Nit', 'LAG', 'TAG', 'Exploit']
FISH = {'Station', 'Nervous', 'Scared', 'Terrified'}
DEFAULT_LINEUP = ['Wizard', 'Hunter', 'AnteMax', 'Maniac', 'Station', 'Nervous']


@dataclass
class Seat:
    name: str
    kind: str              # 'Human' or a bot kind
    bot: object = None
    stack: int = 0
    buyins: int = 1
    won: int = 0           # net chips won this session

    @property
    def is_human(self):
        return self.kind == 'Human'


@dataclass
class HandResult:
    history: object                      # engine HandHistory
    order: list                          # engine seat -> table seat
    net: dict = field(default_factory=dict)   # table seat -> chips won/lost


class _Watched:
    '''Wraps a seat's agent so the observer sees every decision and action.'''

    def __init__(self, inner, table_seat, observer):
        self.inner = inner
        self.name = inner.name
        self.table_seat = table_seat
        self.observer = observer
        self.free_fold = False

    def new_hand(self, hand_id):
        self.inner.new_hand(hand_id)

    def end_hand(self, h):
        self.inner.end_hand(h)

    def receive_cards(self, cards):
        if hasattr(self.inner, 'receive_cards'):
            self.inner.receive_cards(cards)

    def act(self, st):
        if self.observer:
            self.observer.before_action(self.table_seat, st)
        action = Table._sanitize(self.inner.act(st), st)
        if self.observer:
            self.observer.after_action(self.table_seat, st, action)
        return action


class Session:

    def __init__(self, lineup=DEFAULT_LINEUP, structure='ante', buy_in_bb=100, human_name='You',
                 seed=None, history_path=None, rake=0.0, rake_cap=None, label_styles=True):
        '''
        lineup: bot kinds for the other seats (1-8 of them); the human sits in seat 0
        history_path: append every hand to this file in the 1onmyraftpoker format
        label_styles: name bots after their style ("Hunter") or anonymously ("Bot 3")
        '''
        assert 1 <= len(lineup) <= 8
        self.struct = STRUCTURES[structure]
        self.bb = self.struct['big_blind']
        self.buy_in = buy_in_bb * self.bb
        self.table = Table(big_blind=self.bb, small_blind=self.struct['small_blind'],
                           ante=self.struct['ante'], rake=rake, rake_cap=rake_cap)
        self.rng = random.Random(seed)
        self.seats = [Seat(human_name, 'Human', None, self.buy_in)]
        counts = {}
        for i, kind in enumerate(lineup):
            counts[kind] = counts.get(kind, 0) + 1
            if label_styles:
                base = ('Fish: ' + kind) if kind in FISH else kind
                name = base if lineup.count(kind) == 1 else '%s %d' % (base, counts[kind])
            else:
                name = 'Bot %d' % (i + 1)
            bot = make_bot(kind, name, seed=self.rng.randrange(10 ** 9))
            self.seats.append(Seat(name, kind, bot, self.buy_in))
        self.button = self.rng.randrange(len(self.seats))
        self.hand_no = 0
        self.tracker = StatsTracker()
        self.history_path = history_path
        self.started = datetime.now()

    @property
    def human(self):
        return self.seats[0]

    def positions(self):
        '''Position label for each table seat on the coming hand.'''
        from .engine import position_names
        n = len(self.seats)
        names = position_names(n)
        return {(self.button + j) % n: names[j] for j in range(n)}

    def rebuy_busted(self):
        '''Top busted players back up to the buy-in. Returns the seats that rebought.'''
        rebought = []
        for i, s in enumerate(self.seats):
            if s.stack <= 0:
                s.stack = self.buy_in
                s.buyins += 1
                rebought.append(i)
        return rebought

    def play_hand(self, human_agent, observer=None):
        '''Play one hand. human_agent.act(DecisionState) -> Action. Returns a HandResult.'''
        n = len(self.seats)
        self.rebuy_busted()
        order = [(self.button + j) % n for j in range(n)]     # engine seat -> table seat
        agents = []
        for t in order:
            s = self.seats[t]
            inner = human_agent if s.is_human else s.bot
            inner.name = s.name
            agents.append(_Watched(inner, t, observer))
        self.hand_no += 1
        h = self.table.play_hand(agents, deck_seed=self.rng.randrange(10 ** 12), hand_id=self.hand_no,
                                 stacks=[self.seats[t].stack for t in order])
        net = {}
        for j, t in enumerate(order):
            self.seats[t].stack += h.winnings[j]
            self.seats[t].won += h.winnings[j]
            net[t] = h.winnings[j]
        self.tracker.update(h)
        if self.history_path:
            self._save(h, order)
        self.button = (self.button + 1) % n
        return HandResult(h, order, net)

    def _save(self, h, order):
        hero = order.index(0)
        text = write_hand(h, self.hand_no, datetime.now(), 'home', [t + 1 for t in order],
                          max_seats=len(self.seats), sb=self.struct['small_blind'], bb=self.bb,
                          ante=self.struct['ante'], hero=hero,
                          names=['Hero' if t == 0 else self.seats[t].name.replace(': ', '_').replace(' ', '_') for t in order])
        os.makedirs(os.path.dirname(os.path.abspath(self.history_path)), exist_ok=True)
        with open(self.history_path, 'a', encoding='utf-8') as f:
            f.write(text)

    def hud(self, seat_index, min_hands=1):
        '''Short HUD string for a seat: VPIP/PFR/3B, AF, hands.'''
        p = self.tracker.players.get(self.seats[seat_index].name)
        if not p or p.hands < min_hands:
            return ''
        def pct(k):
            r = p.rate(k, shrink=False)
            return '-' if r != r else '%d' % round(100 * r)
        return '%s/%s/%s  AF %.1f  (%d)' % (pct('vpip'), pct('pfr'), pct('three_bet'), p.af(), p.hands)


class CallingHuman:
    '''Stand-in human for tests: checks or calls everything.'''
    name = 'You'

    def new_hand(self, hand_id):
        pass

    def end_hand(self, h):
        pass

    def act(self, st):
        return Action(CALL if st.to_call else CHECK)
