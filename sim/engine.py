'''
Headless no-limit hold'em engine for bot simulations.

One `play_hand` call deals and plays a full hand between bots, enforcing
NLHE betting rules (blinds, min-raise, short all-ins, side pots), and
returns a `HandHistory` of public events that the stats tracker consumes.

Stacks are reset every hand (cash-game style), which keeps results
comparable across long simulations.
'''
import random
from dataclasses import dataclass, field
from itertools import combinations

from .cards import DECK, evaluate

PREFLOP, FLOP, TURN, RIVER = 'preflop', 'flop', 'turn', 'river'
STREETS = [PREFLOP, FLOP, TURN, RIVER]

FOLD, CHECK, CALL, BET, RAISE = 'fold', 'check', 'call', 'bet', 'raise'


def position_names(n):
    '''Position labels in seat order starting from the button.'''
    if n == 2:
        return ['BTN', 'BB']
    base = {3: ['BTN', 'SB', 'BB'],
            4: ['BTN', 'SB', 'BB', 'UTG'],
            5: ['BTN', 'SB', 'BB', 'UTG', 'CO'],
            6: ['BTN', 'SB', 'BB', 'UTG', 'MP', 'CO']}
    if n in base:
        return base[n]
    middle = ['UTG'] + ['UTG+%d' % i for i in range(1, n - 5)] + ['MP', 'HJ', 'CO']
    return ['BTN', 'SB', 'BB'] + middle[-(n - 3):]


@dataclass
class Action:
    '''What a bot returns. `amount` is the total bet size *to* for bet/raise.'''
    kind: str
    amount: int = 0


@dataclass
class ActionEvent:
    street: str
    seat: int
    kind: str            # fold / check / call / bet / raise (blinds are not actions)
    added: int           # chips put in by this action
    to: int              # player's total street commitment after the action
    to_call: int         # amount the player faced before acting
    pot: int             # pot before the action
    all_in: bool = False


@dataclass
class HandHistory:
    hand_id: int
    names: list               # player name per seat
    positions: list           # position label per seat
    big_blind: int
    hole: list                # hole cards per seat (private; only revealed at showdown)
    board: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    showdown: list = field(default_factory=list)   # seats that showed down
    winnings: list = None                          # net chips per seat
    ev_winnings: list = None   # all-in EV net chips (set only when players were all-in before the river)
    saw_street: dict = field(default_factory=dict)  # street -> seats still in at its start


@dataclass
class DecisionState:
    '''Everything a bot may look at when it acts (only public info + its own cards).'''
    hand_id: int
    street: str
    seat: int
    position: str
    hole: list
    board: list
    pot: int                 # includes all current-street bets
    to_call: int
    stack: int               # chips behind
    committed: int           # this street
    current_bet: int
    min_raise_to: int
    max_raise_to: int
    can_raise: bool
    big_blind: int
    n_active: int            # players not folded
    active_seats: list
    names: list
    positions: list
    stacks: list
    street_actions: list     # ActionEvents this street so far
    history: list            # all ActionEvents this hand so far
    preflop_aggressor: int   # seat of last preflop raiser, or None
    raises_this_street: int

    def legal(self):
        kinds = [FOLD] if self.to_call > 0 else [CHECK]
        if self.to_call > 0:
            kinds.append(CALL)
        if self.can_raise and self.stack > self.to_call:
            kinds.append(RAISE if self.current_bet > 0 else BET)
        return kinds


class Table:
    '''
    Plays hands between a list of bots. Seat 0 is the button on every hand;
    rotate the bot list between hands to move the button (the match runner does this).
    '''

    def __init__(self, big_blind=2, small_blind=None, stack_bb=100):
        self.bb = big_blind
        self.sb = small_blind if small_blind is not None else big_blind // 2
        self.start_stack = stack_bb * big_blind

    def play_hand(self, bots, deck_seed, hand_id=0, stacks=None):
        n = len(bots)
        assert 2 <= n <= 9
        deck = DECK[:]
        random.Random(deck_seed).shuffle(deck)
        positions = position_names(n)
        names = [b.name for b in bots]
        # Cards are dealt by position so a given seed gives each seat the same cards
        # no matter which bot sits there (needed for duplicate matches).
        hole = [[deck[2 * i], deck[2 * i + 1]] for i in range(n)]
        board_cards = deck[2 * n:2 * n + 5]

        h = HandHistory(hand_id, names, positions, self.bb, hole)
        stacks = list(stacks) if stacks else [self.start_stack] * n
        invested = [0] * n
        folded = [False] * n

        def post(seat, amt):
            amt = min(amt, stacks[seat])
            stacks[seat] -= amt
            invested[seat] += amt
            return amt

        if n == 2:
            sb_seat, bb_seat, first_pre = 0, 1, 0
        else:
            sb_seat, bb_seat, first_pre = 1, 2, 3 % n
        street_bet = [0] * n
        street_bet[sb_seat] = post(sb_seat, self.sb)
        street_bet[bb_seat] = post(bb_seat, self.bb)

        for b in bots:
            b.new_hand(hand_id)

        pf_aggressor = None
        allin_known = None   # board cards known when the remaining players got all-in
        for street_idx, street in enumerate(STREETS):
            if street_idx > 0:
                h.board = board_cards[:{FLOP: 3, TURN: 4, RIVER: 5}[street]]
                street_bet = [0] * n
            in_hand = [i for i in range(n) if not folded[i]]
            h.saw_street[street] = in_hand
            if len(in_hand) == 1:
                break
            can_act = [i for i in in_hand if stacks[i] > 0]
            nothing_to_call = all(street_bet[i] >= max(street_bet) for i in can_act)
            if len(can_act) <= 1 and nothing_to_call:
                if allin_known is None:
                    allin_known = {PREFLOP: 0, FLOP: 0, TURN: 3, RIVER: 4}[street]
                continue  # everyone (but at most one) is all-in: run the board out
            # preflop: UTG (button heads-up); postflop: first seat left of the button
            first = first_pre if street == PREFLOP else 1
            agg = self._betting_round(bots, h, street, first, stacks, invested, street_bet,
                                      folded, pf_aggressor)
            if street == PREFLOP:
                pf_aggressor = agg
            if sum(not f for f in folded) == 1:
                break

        h.winnings = self._settle(h, invested, folded)
        if h.showdown and allin_known is not None:
            h.ev_winnings = self._allin_ev(h, invested, folded, deck, allin_known, deck_seed)
        for b in bots:
            b.end_hand(h)
        return h

    def _betting_round(self, bots, h, street, first, stacks, invested, street_bet, folded, pf_agg):
        n = len(bots)
        current_bet = max(street_bet)
        last_raise = self.bb  # minimum raise increment
        # players who must still act; reopened to everyone else on a full raise
        needs = [i for i in range(n) if not folded[i] and stacks[i] > 0]
        can_raise = {i: True for i in needs}
        acted_since_full = set()  # who has acted since the last full raise
        street_actions = []
        aggressor = None
        raises = 1 if street == PREFLOP else 0  # the big blind counts as the first "raise"
        order = [(first + k) % n for k in range(n)]
        pending = [i for i in order if i in needs]

        while pending:
            seat = pending.pop(0)
            if folded[seat] or stacks[seat] == 0:
                continue
            active = [i for i in range(n) if not folded[i]]
            if len(active) == 1:
                break
            to_call = min(current_bet - street_bet[seat], stacks[seat])
            others_can_act = any(stacks[i] > 0 for i in active if i != seat)
            st = DecisionState(
                hand_id=h.hand_id, street=street, seat=seat, position=h.positions[seat],
                hole=h.hole[seat], board=list(h.board), pot=sum(invested), to_call=to_call,
                stack=stacks[seat], committed=street_bet[seat], current_bet=current_bet,
                min_raise_to=min(current_bet + last_raise, street_bet[seat] + stacks[seat]),
                max_raise_to=street_bet[seat] + stacks[seat],
                can_raise=can_raise.get(seat, True) and others_can_act,
                big_blind=self.bb, n_active=len(active), active_seats=active,
                names=h.names, positions=h.positions, stacks=list(stacks),
                street_actions=list(street_actions), history=list(h.actions),
                preflop_aggressor=pf_agg, raises_this_street=raises)
            act = self._sanitize(bots[seat].act(st), st)
            pot_before = sum(invested)

            if act.kind == FOLD:
                folded[seat] = True
                ev = ActionEvent(street, seat, FOLD, 0, street_bet[seat], to_call, pot_before)
            elif act.kind in (CHECK, CALL):
                added = to_call
                stacks[seat] -= added
                invested[seat] += added
                street_bet[seat] += added
                ev = ActionEvent(street, seat, act.kind, added, street_bet[seat], to_call,
                                 pot_before, all_in=stacks[seat] == 0)
            else:
                target = act.amount
                added = target - street_bet[seat]
                stacks[seat] -= added
                invested[seat] += added
                street_bet[seat] = target
                raise_size = target - current_bet
                full = raise_size >= last_raise
                if full:
                    last_raise = raise_size
                current_bet = target
                raises += 1
                aggressor = seat
                ev = ActionEvent(street, seat, act.kind, added, target, to_call, pot_before,
                                 all_in=stacks[seat] == 0)
                # everyone else still in with chips must respond
                pending = [(seat + k) % n for k in range(1, n)]
                pending = [i for i in pending if not folded[i] and stacks[i] > 0]
                if full:
                    acted_since_full = set()
                    for i in pending:
                        can_raise[i] = True
                else:
                    # a short all-in doesn't reopen raising for players who already acted
                    for i in pending:
                        can_raise[i] = can_raise.get(i, True) and i not in acted_since_full
            acted_since_full.add(seat)
            street_actions.append(ev)
            h.actions.append(ev)
        return aggressor

    @staticmethod
    def _sanitize(act, st):
        '''Coerce whatever a bot returns into a legal action.'''
        if act is None:
            act = Action(CHECK if st.to_call == 0 else FOLD)
        kind = act.kind
        if kind in (BET, RAISE):
            if not st.can_raise or st.stack <= st.to_call:
                kind = CALL if st.to_call > 0 else CHECK
            else:
                amount = max(st.min_raise_to, min(int(act.amount), st.max_raise_to))
                return Action(RAISE if st.current_bet > 0 else BET, amount)
        if kind == FOLD and st.to_call == 0:
            kind = CHECK
        if kind == CHECK and st.to_call > 0:
            kind = FOLD
        if kind == CALL and st.to_call == 0:
            kind = CHECK
        return Action(kind)

    def _settle(self, h, invested, folded):
        n = len(invested)
        alive = [i for i in range(n) if not folded[i]]
        if len(alive) == 1:
            won = [0] * n
            won[alive[0]] = sum(invested)
        else:
            h.showdown = alive
            won = self._payout(h.hole, h.board, invested, alive)
        return [won[i] - invested[i] for i in range(n)]

    def _allin_ev(self, h, invested, folded, deck, known, seed, samples=300):
        '''Average payout over all runouts from the point the players were all-in.'''
        n = len(invested)
        alive = [i for i in range(n) if not folded[i]]
        dealt = {c for hc in h.hole for c in hc} | set(h.board[:known])
        rest = [c for c in deck if c not in dealt]
        k = 5 - known
        if k <= 2:
            runouts = list(combinations(rest, k))
        else:
            rng = random.Random(seed * 7919 + 1)
            runouts = [rng.sample(rest, k) for _ in range(samples)]
        total = [0.0] * n
        for ro in runouts:
            won = self._payout(h.hole, h.board[:known] + list(ro), invested, alive)
            for i in range(n):
                total[i] += won[i]
        return [total[i] / len(runouts) - invested[i] for i in range(n)]

    @staticmethod
    def _payout(hole, board, invested, alive):
        n = len(invested)
        won = [0] * n
        values = {i: evaluate(hole[i] + board) for i in alive}
        levels = sorted(set(invested[i] for i in range(n) if invested[i] > 0))
        prev = 0
        for lvl in levels:
            pot = sum(min(invested[i], lvl) - min(invested[i], prev) for i in range(n))
            eligible = [i for i in alive if invested[i] >= lvl]
            if not eligible:  # only folded players put in this much; give it to the best remaining
                eligible = [i for i in alive if invested[i] == max(invested[j] for j in alive)]
            best = max(values[i] for i in eligible)
            winners = [i for i in eligible if values[i] == best]
            share, odd = divmod(pot, len(winners))
            for k, i in enumerate(sorted(winners, key=lambda s: (s - 1) % n)):
                won[i] += share + (1 if k < odd else 0)
            prev = lvl
        return won
