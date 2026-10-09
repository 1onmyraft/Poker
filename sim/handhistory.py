'''
Text hand histories in the "1onmyraftpoker" format.

- `write_hand` renders an engine HandHistory as text (7-max ante games, straddles,
  uncalled-bet returns, rake, side pots).
- `parse_file` / `parse_hands` read that format back into `ParsedHand` objects,
  including cash-outs, mucks and run-it-twice hands.
- `replay` pushes a ParsedHand back through the engine so bots can be asked what
  they would have done at each decision; it verifies the engine reproduces every
  logged action and the total pot.

Amounts are handled in integer cents internally.
'''
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .cards import evaluate
from .engine import (Table, Action, PREFLOP, FLOP, TURN, RIVER, FOLD, CHECK, CALL, BET,
                     RAISE)

SITE = '1onmyraftpoker'
CUR = '₮'
HAND_NAMES = ['High Card', 'One Pair', 'Two Pair', 'Three Of A Kind', 'Straight', 'Flush',
              'Full House', 'Four Of A Kind', 'Straight Flush']
STREET_LABEL = {PREFLOP: 'before Flop', FLOP: 'on the Flop', TURN: 'on the Turn', RIVER: 'on the River'}


def money(cents):
    return CUR + (str(cents // 100) if cents % 100 == 0 else '%.2f' % (cents / 100))


def cents(text):
    return int(round(float(text) * 100))


def anon_name(rng):
    return '%08x' % rng.getrandbits(32)


# --------------------------------------------------------------------------- writer

def write_hand(h, hand_no, when, table_name, seat_numbers, max_seats=7, sb=10, bb=10, ante=10,
               hero=None, names=None, cashouts=None):
    '''
    PARAMETERS:
        h: engine HandHistory (engine seat 0 = button)
        seat_numbers: table seat number for each engine seat
        hero: engine seat whose hole cards are shown in "Dealt to" (None = nobody)
        names: display name per engine seat (defaults to h.names)
        cashouts: {engine seat: (payout, fee)} for players who took the all-in cash out;
                  the house keeps whatever they would have collected

    RETURN: string
    '''
    n = len(h.names)
    names = names or h.names
    order = sorted(range(n), key=lambda i: seat_numbers[i])   # table order
    out = []
    out.append('%s Hand #%d: NLH (%s/%s/%s) %s PDT' % (
        SITE, hand_no, money(sb), money(bb), money(ante), when.strftime('%Y/%m/%d %H:%M:%S')))
    out.append("Table '%s' %d-max Seat #%d is the button" % (table_name, max_seats, seat_numbers[0]))
    for i in order:
        out.append('Seat %d: %s (%s in chips)' % (seat_numbers[i], names[i], money(h.start_stacks[i])))
    for seat, kind, amt in h.posts:
        if kind == 'ante':
            out.append('%s: posts ante %s' % (names[seat], money(amt)))
    labels = {'sb': 'small blind', 'bb': 'big blind', 'auto_bb': 'auto big blind'}
    for seat, kind, amt in h.posts:
        if kind in labels:
            out.append('%s: posts %s %s' % (names[seat], labels[kind], money(amt)))
    out.append('*** HOLE CARDS ***')
    for i in order:
        if i == hero:
            out.append('Dealt to %s [%s]' % (names[i], ' '.join(h.hole[i])))
        else:
            out.append('Dealt to %s' % names[i])
    for seat, kind, amt in h.posts:
        if kind == 'straddle':
            out.append('%s: STRADDLE %s' % (names[seat], money(amt)))

    fold_street = {}
    streets = [PREFLOP, FLOP, TURN, RIVER]
    board_at = {FLOP: 3, TURN: 4, RIVER: 5}
    for street in streets:
        acts = [a for a in h.actions if a.street == street]
        if street != PREFLOP:
            if len(h.board) < board_at[street]:
                break
            b = h.board
            if street == FLOP:
                out.append('*** FLOP *** [%s]' % ' '.join(b[:3]))
            elif street == TURN:
                out.append('*** TURN *** [%s] [%s]' % (' '.join(b[:3]), b[3]))
            else:
                out.append('*** RIVER *** [%s] [%s]' % (' '.join(b[:4]), b[4]))
        for a in acts:
            nm = names[a.seat]
            if a.kind == FOLD:
                fold_street[a.seat] = street
                out.append('%s: folds' % nm)
            elif a.all_in:
                out.append('%s: ALLIN %s' % (nm, money(a.added)))
            elif a.kind == CHECK:
                out.append('%s: checks' % nm)
            elif a.kind == CALL:
                out.append('%s: calls %s' % (nm, money(a.added)))
            elif a.kind == BET:
                out.append('%s: bets %s' % (nm, money(a.added)))
            else:
                out.append('%s: raises %s to %s' % (nm, money(a.added - a.to_call), money(a.to)))
        for st, seat, amt in h.returns:
            if st == street:
                out.append('%s: RETURN %s' % (names[seat], money(amt)))

    out.append('*** SHOWDOWN ***')
    cashouts = cashouts or {}
    shown = set()
    won_total = [0] * n
    for award in h.pot_awards:
        for seat, amt in award:
            if seat in h.showdown and seat not in shown:
                shown.add(seat)
                out.append('%s: shows [%s] (%s)' % (names[seat], ' '.join(h.hole[seat]), _hand_name(h, seat)))
            if amt and seat not in cashouts:
                out.append('%s collected %s from pot' % (names[seat], money(amt)))
                won_total[seat] += amt
    for seat in h.showdown:
        if seat not in shown:
            out.append('%s: shows [%s] (%s)' % (names[seat], ' '.join(h.hole[seat]), _hand_name(h, seat)))
    for seat, (paid, fee) in cashouts.items():
        out.append('%s cashed out the hand for %s | Cash Out Fee %s' % (names[seat], money(paid), money(fee)))

    out.append('*** SUMMARY ***')
    out.append('Total pot %s | Rake %s' % (money(sum(h.invested)), money(h.rake)))
    out.append('Hand was run once')
    out.append('Board [ %s ]' % ' '.join(h.board) if h.board else 'Board [  ]')
    out.append('Game ended: %s PDT' % (when + timedelta(seconds=45)).strftime('%Y/%m/%d %H:%M:%S'))
    for i in order:
        line = 'Seat %d: %s ' % (seat_numbers[i], names[i])
        if i in cashouts:
            line += 'showed [%s] and cashed out for %s | Cash Out Fee %s' % (
                ' '.join(h.hole[i]), money(cashouts[i][0]), money(cashouts[i][1]))
        elif i in h.showdown:
            cards = ' '.join(h.hole[i])
            if won_total[i]:
                line += 'showed [%s] and won (%s) with %s' % (cards, money(won_total[i]), _hand_name(h, i))
            else:
                line += 'showed [%s] and lost with %s' % (cards, _hand_name(h, i))
        elif won_total[i]:
            line += 'won (%s)' % money(won_total[i])
        else:
            st = fold_street.get(i, PREFLOP)
            line += 'folded %s' % STREET_LABEL[st] + (" (didn't bet)" if st == PREFLOP else '')
        out.append(line)
    return '\n'.join(out) + '\n\n\n'


def _hand_name(h, seat):
    return HAND_NAMES[evaluate(h.hole[seat] + h.board)[0]]


# --------------------------------------------------------------------------- parser

@dataclass
class ParsedAction:
    street: str
    name: str
    kind: str        # folds checks calls bets raises ALLIN STRADDLE
    added: int       # chips put in by this action
    to: int = 0      # street total after the action (raises)


@dataclass
class ParsedHand:
    hand_id: str
    when: str
    table: str
    max_seats: int
    button_seat: int
    sb: int
    bb: int
    ante: int
    seats: dict = field(default_factory=dict)       # seat no -> (name, stack)
    posts: list = field(default_factory=list)       # (name, kind, amount)
    hero: str = None
    hero_cards: list = None
    actions: list = field(default_factory=list)     # ParsedAction (STRADDLE included)
    returns: list = field(default_factory=list)     # (street, name, amount)
    board: list = field(default_factory=list)       # first run if run twice
    shows: dict = field(default_factory=dict)       # name -> cards
    mucks: set = field(default_factory=set)
    collected: dict = field(default_factory=dict)   # name -> total collected
    cashouts: dict = field(default_factory=dict)    # name -> amount received
    total_pot: int = 0
    rake: int = 0
    run_twice: bool = False

    def invested(self):
        '''Total chips each player put in (posts + actions - returns).'''
        inv = {}
        for name, _, amt in self.posts:
            inv[name] = inv.get(name, 0) + amt
        for a in self.actions:
            inv[a.name] = inv.get(a.name, 0) + a.added
        for _, name, amt in self.returns:
            inv[name] = inv.get(name, 0) - amt
        return inv

    def net(self, name):
        '''Net result for a player: collected + cash-out - invested.'''
        return self.collected.get(name, 0) + self.cashouts.get(name, 0) - self.invested().get(name, 0)


_RE = {
    'header': re.compile(r'^(\S+) Hand #(\d+): NLH \(₮([\d.]+)/₮([\d.]+)/₮([\d.]+)\) (\d{4}/\d\d/\d\d \d\d:\d\d:\d\d)'),
    'table': re.compile(r"^Table '([^']+)' (\d+)-max Seat #(\d+) is the button"),
    'seat': re.compile(r'^Seat (\d+): (\S+) \(₮([\d.]+) in chips\)'),
    'post': re.compile(r'^(\S+): posts (ante|small blind|big blind|auto big blind) ₮([\d.]+)'),
    'dealt': re.compile(r'^Dealt to (\S+)(?: \[(.+)\])?$'),
    'straddle': re.compile(r'^(\S+): STRADDLE ₮([\d.]+)'),
    'action': re.compile(r'^(\S+): (folds|checks|calls|bets|raises|ALLIN)(?: ₮([\d.]+))?(?: to ₮([\d.]+))?$'),
    'return': re.compile(r'^(\S+): RETURN ₮([\d.]+)'),
    'street': re.compile(r'^\*\*\* (FIRST |SECOND )?(FLOP|TURN|RIVER) \*\*\* (.*)$'),
    'shows': re.compile(r'^(\S+): shows \[(.+?)\]'),
    'mucks': re.compile(r'^(\S+): mucks hand'),
    'collected': re.compile(r'^(\S+) collected ₮([\d.]+) from pot'),
    'cashout': re.compile(r'^(\S+) cashed out the hand for ₮([\d.]+)'),
    'total': re.compile(r'^Total pot ₮([\d.]+) \| Rake ₮([\d.]+)'),
    'run': re.compile(r'^Hand was run (\S+)'),
}
_POST_KIND = {'ante': 'ante', 'small blind': 'sb', 'big blind': 'bb', 'auto big blind': 'auto_bb'}


def parse_file(path):
    with open(path, encoding='utf-8') as f:
        return parse_hands(f.read())


def parse_hands(text):
    hands, cur, street, committed, cash_seen = [], None, None, {}, set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _RE['header'].match(line)
        if m:
            cur = ParsedHand(m.group(2), m.group(6), '', 0, 0, cents(m.group(3)),
                             cents(m.group(4)), cents(m.group(5)))
            hands.append(cur)
            street, committed, cash_seen = None, {}, set()
            continue
        if cur is None:
            continue
        if (m := _RE['table'].match(line)):
            cur.table, cur.max_seats, cur.button_seat = m.group(1), int(m.group(2)), int(m.group(3))
        elif street is None and (m := _RE['seat'].match(line)):
            cur.seats[int(m.group(1))] = (m.group(2), cents(m.group(3)))
        elif (m := _RE['post'].match(line)):
            kind, amt = _POST_KIND[m.group(2)], cents(m.group(3))
            cur.posts.append((m.group(1), kind, amt))
            if kind != 'ante':
                committed[m.group(1)] = committed.get(m.group(1), 0) + amt
        elif line == '*** HOLE CARDS ***':
            street = PREFLOP
        elif (m := _RE['dealt'].match(line)):
            if m.group(2):
                cur.hero, cur.hero_cards = m.group(1), m.group(2).split()
        elif (m := _RE['straddle'].match(line)):
            amt = cents(m.group(2))
            committed[m.group(1)] = committed.get(m.group(1), 0) + amt
            cur.actions.append(ParsedAction(street, m.group(1), 'STRADDLE', amt, committed[m.group(1)]))
        elif (m := _RE['action'].match(line)):
            name, kind = m.group(1), m.group(2)
            prev = committed.get(name, 0)
            if kind == 'raises':
                to = cents(m.group(4))
                added = to - prev
            else:
                added = cents(m.group(3)) if m.group(3) else 0
                to = prev + added
            committed[name] = to
            cur.actions.append(ParsedAction(street, name, kind, added, to))
        elif (m := _RE['return'].match(line)):
            cur.returns.append((street, m.group(1), cents(m.group(2))))
        elif (m := _RE['street'].match(line)):
            run, st = m.group(1), m.group(2).lower()
            if run == 'SECOND ':
                cur.run_twice = True
                street = st
                continue
            cards = re.findall(r'\[([^\]]+)\]', m.group(3))
            cur.board = ' '.join(cards).split()
            street, committed = st, {}
        elif (m := _RE['shows'].match(line)):
            cur.shows[m.group(1)] = m.group(2).split()
        elif (m := _RE['mucks'].match(line)):
            cur.mucks.add(m.group(1))
        elif (m := _RE['collected'].match(line)):
            cur.collected[m.group(1)] = cur.collected.get(m.group(1), 0) + cents(m.group(2))
        elif (m := _RE['cashout'].match(line)):
            # the same cash-out is printed once per pot; count it once
            if (m.group(1), m.group(2)) not in cash_seen:
                cash_seen.add((m.group(1), m.group(2)))
                cur.cashouts[m.group(1)] = cur.cashouts.get(m.group(1), 0) + cents(m.group(2))
        elif (m := _RE['total'].match(line)):
            cur.total_pot, cur.rake = cents(m.group(1)), cents(m.group(2))
        elif (m := _RE['run'].match(line)):
            cur.run_twice = cur.run_twice or m.group(1) != 'once'
    return hands


# --------------------------------------------------------------------------- replay

class ReplayError(Exception):
    pass


class _Scripted:
    '''Replays one player's logged actions inside the engine.'''

    free_fold = True   # logs can contain folds where a check was possible

    def __init__(self, name, actions):
        self.name = name
        self.queue = [a for a in actions if a.kind != 'STRADDLE']

    def new_hand(self, hand_id):
        pass

    def end_hand(self, h):
        pass

    def next_action(self, st):
        if not self.queue:
            raise ReplayError('%s has no logged action on the %s' % (self.name, st.street))
        a = self.queue.pop(0)
        if a.street != st.street:
            raise ReplayError('%s acted on the %s, log says %s' % (self.name, st.street, a.street))
        if a.kind == 'folds':
            return Action(FOLD)
        if a.kind == 'checks':
            return Action(CHECK)
        if a.kind == 'calls':
            return Action(CALL)
        if a.kind == 'ALLIN':
            return Action(CALL) if a.added <= st.to_call else Action(RAISE, st.max_raise_to)
        return Action(RAISE if a.kind == 'raises' else BET, st.committed + a.added)

    def act(self, st):
        return self.next_action(st)


class _Shadow(_Scripted):
    '''Plays Hero's logged actions while recording what candidate bots would do.'''

    def __init__(self, name, actions, candidates):
        super().__init__(name, actions)
        self.candidates = candidates
        self.decisions = []   # (DecisionState, hero Action, {bot name: Action})

    def new_hand(self, hand_id):
        for c in self.candidates:
            c.new_hand(hand_id)

    def end_hand(self, h):
        for c in self.candidates:
            c.end_hand(h)

    def act(self, st):
        hero = Table._sanitize(self.next_action(st), st, free_fold=True)
        picks = {c.name: Table._sanitize(c.act(st), st) for c in self.candidates}
        self.decisions.append((st, hero, picks))
        return hero


def replay(ph, candidates=(), seed=0):
    '''
    Re-run a parsed hand through the engine.

    RETURN: (engine HandHistory, list of Hero decisions [(state, hero_action, {bot: action})])
    Raises ReplayError if the engine can't reproduce the log exactly.
    '''
    # run-it-twice hands replay fine on the first board: no decisions happen after the all-in
    table_seats = sorted(ph.seats)
    if ph.button_seat not in table_seats:
        raise ReplayError('button seat is empty')
    b = table_seats.index(ph.button_seat)
    seat_nos = table_seats[b:] + table_seats[:b]          # engine seat 0 = button
    names = [ph.seats[s][0] for s in seat_nos]
    idx = {nm: i for i, nm in enumerate(names)}
    n = len(names)

    blinds = {kind: name for name, kind, _ in ph.posts if kind in ('sb', 'bb')}
    exp_sb, exp_bb = (names[0], names[1]) if n == 2 else (names[1], names[2])
    if blinds.get('sb') != exp_sb or blinds.get('bb') != exp_bb:
        raise ReplayError('blinds not in standard seats')
    sb_amt = next(a for _, k, a in ph.posts if k == 'sb')
    extra = [(idx[nm], amt, kind) for nm, kind, amt in ph.posts if kind == 'auto_bb']
    extra += [(idx[a.name], a.added, 'straddle') for a in ph.actions if a.kind == 'STRADDLE']

    hole = {idx[nm]: cards for nm, cards in ph.shows.items()}
    if ph.hero:
        hole[idx[ph.hero]] = ph.hero_cards
    bots = []
    shadow = None
    for nm in names:
        acts = [a for a in ph.actions if a.name == nm]
        if nm == ph.hero:
            shadow = _Shadow(nm, acts, candidates)
            bots.append(shadow)
        else:
            bots.append(_Scripted(nm, acts))

    table = Table(big_blind=ph.bb, small_blind=sb_amt, ante=ph.ante, rake=0.0)
    h = table.play_hand(bots, deck_seed=seed, stacks=[ph.seats[s][1] for s in seat_nos],
                        posts=extra, deal={'hole': hole, 'board': ph.board})

    # verify the engine reproduced the log
    logged = [a for a in ph.actions if a.kind != 'STRADDLE']
    if len(logged) != len(h.actions):
        raise ReplayError('engine played %d actions, log has %d' % (len(h.actions), len(logged)))
    for e, a in zip(h.actions, logged):
        if names[e.seat] != a.name or e.added != a.added:
            raise ReplayError('action mismatch: engine %s %s %d vs log %s %s %d' % (
                names[e.seat], e.kind, e.added, a.name, a.kind, a.added))
    if ph.total_pot and sum(h.invested) != ph.total_pot:
        raise ReplayError('pot %d != logged %d' % (sum(h.invested), ph.total_pot))
    return h, (shadow.decisions if shadow else [])


# --------------------------------------------------------------------------- generator

def generate(bots, n_hands, seed=0, hero_index=0, sb=10, bb=10, ante=10, rake=0.05, rake_cap=150,
             stack_range=(40, 120), straddle_rate=0.08, max_seats=7, anonymize=True,
             start=datetime(2026, 10, 7, 0, 33, 33), first_hand_no=149875801823):
    '''
    Play n_hands at a 7-max ante table and return them as one text block in this format.
    Bot i sits in table seat i + 1; the button moves one seat per hand.
    '''
    rng = random.Random(seed)
    table = Table(big_blind=bb, small_blind=sb, ante=ante, rake=rake, rake_cap=rake_cap)
    n = len(bots)
    table_name = str(rng.randint(100000, 999999))
    out, when = [], start
    histories = []
    for k in range(n_hands):
        btn = k % n
        order = [(btn + j) % n for j in range(n)]          # engine seat -> bot index
        seated = [bots[i] for i in order]
        stacks = [bb * rng.randint(*stack_range) for _ in range(n)]
        posts = []
        if n > 3 and rng.random() < straddle_rate:
            posts.append((3, 2 * bb, 'straddle'))
        h = table.play_hand(seated, deck_seed=seed * 1_000_003 + k, hand_id=k, stacks=stacks,
                            posts=posts)
        histories.append((h, order))
        names = []
        for j, i in enumerate(order):
            if i == hero_index:
                names.append('Hero')
            else:
                names.append(anon_name(rng) if anonymize else bots[i].name)
        hero_seat = order.index(hero_index) if hero_index is not None else None
        out.append(write_hand(h, first_hand_no + k, when, table_name, [i + 1 for i in order],
                              max_seats, sb, bb, ante, hero=hero_seat, names=names))
        when += timedelta(seconds=rng.randint(40, 70))
    return ''.join(out), histories
