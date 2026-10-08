'''
Rule-based bots with tunable parameters, a zoo of archetypes, and an
adaptive ExploitBot that models opponents from its own StatsTracker.

Preflop ranges are expressed as "top X fraction of all combos" using the
same hand ordering as misc.pf_compact. Postflop decisions compare a cheap
strength estimate (sim/strength.py) to pot odds, plus per-bot margins.
'''
import random
from dataclasses import dataclass, replace

from .engine import Action, PREFLOP, FLOP, FOLD, CHECK, CALL, BET, RAISE
from . import pushfold
from .ranges import RangeTracker, equity
from .stats import StatsTracker
from .cards import RANK_VALUE
from .strength import preflop_strength, postflop_strength

LATE = ('CO', 'BTN', 'SB')
BLINDS = ('SB', 'BB')
# 0 = first to act, 1 = button (used by pos_spread)
POS_RANK = {'UTG': 0.0, 'UTG+1': 0.1, 'UTG+2': 0.2, 'MP': 0.35, 'HJ': 0.55, 'CO': 0.75,
            'BTN': 1.0, 'SB': 0.8, 'BB': 0.0}


@dataclass(frozen=True)
class Params:
    # preflop (fractions of all combos)
    open: float = 0.18         # open-raise range when first in
    steal_mult: float = 1.8    # widen opens from CO/BTN/SB when folded to
    limp: float = 0.0          # extra range that limps instead of folding
    call_open: float = 0.10    # flat range vs a single raise (on top of 3-bets)
    bb_defend: float = 1.5     # multiplier on call_open from the big blind
    threebet: float = 0.05
    call_3bet: float = 0.07
    fourbet: float = 0.025
    open_size: float = 2.5     # in big blinds
    pos_spread: float = 0.0    # widen opens toward the button: open * (1 + pos_spread * rank)
    iso: float = 1.0           # multiplier on the open range when raising over limpers in position
    iso_per_limper: float = 1.0  # extra big blinds added to the raise per limper
    # postflop
    value: float = 0.66        # strength needed to bet for value
    bluff: float = 0.12        # chance to bet a weak hand when checked to
    cbet: float = 0.65         # chance the preflop raiser c-bets the flop
    semibluff: float = 0.5     # chance to bet a draw-ish medium hand
    call_margin: float = 0.12  # extra equity required above pot odds to call
    fear: float = 0.0          # extra equity required per pot-sized bet faced
    raise_value: float = 0.85  # strength needed to raise a bet
    raise_bluff: float = 0.03  # chance to bluff-raise
    bet_size: float = 0.66     # fraction of pot
    # "smart" mode: push/fold equilibrium charts when short, and postflop equity against
    # each opponent's estimated range (with card removal) instead of the strength heuristic
    smart: bool = False
    eq_samples: int = 200


PRESETS = {
    # solid baseline
    'TAG': Params(),
    'LAG': Params(open=0.28, steal_mult=1.7, call_open=0.14, threebet=0.09, call_3bet=0.12,
                  fourbet=0.04, value=0.60, bluff=0.25, cbet=0.80, semibluff=0.7,
                  call_margin=0.07, raise_value=0.80, raise_bluff=0.08),
    'Nit': Params(open=0.09, steal_mult=1.3, call_open=0.04, bb_defend=1.2, threebet=0.025,
                  call_3bet=0.03, fourbet=0.02, value=0.75, bluff=0.03, cbet=0.45,
                  semibluff=0.2, call_margin=0.20, fear=0.2, raise_value=0.90, raise_bluff=0.0),
    'Station': Params(open=0.10, steal_mult=1.2, limp=0.35, call_open=0.40, bb_defend=1.3,
                      threebet=0.02, call_3bet=0.30, fourbet=0.01, value=0.80, bluff=0.02,
                      cbet=0.30, semibluff=0.1, call_margin=-0.12, raise_value=0.93,
                      raise_bluff=0.0),
    'Maniac': Params(open=0.55, steal_mult=1.4, call_open=0.30, threebet=0.25, call_3bet=0.30,
                     fourbet=0.12, open_size=3.5, value=0.45, bluff=0.50, cbet=0.90,
                     semibluff=0.8, call_margin=0.0, raise_value=0.65, raise_bluff=0.20,
                     bet_size=1.0),
    # Low-level "scared" bots: play too few hands, rarely bluff, and fold to pressure.
    # Higher level = more scared. Fear makes them fold more as bets get bigger.
    'Nervous': Params(open=0.14, steal_mult=1.3, limp=0.10, call_open=0.10, bb_defend=1.2,
                      threebet=0.02, call_3bet=0.03, fourbet=0.015, value=0.75, bluff=0.05,
                      cbet=0.40, semibluff=0.15, call_margin=0.12, fear=0.35, raise_value=0.92,
                      raise_bluff=0.0, bet_size=0.5),
    'Scared': Params(open=0.10, steal_mult=1.2, limp=0.15, call_open=0.08, bb_defend=1.1,
                     threebet=0.015, call_3bet=0.02, fourbet=0.012, value=0.82, bluff=0.02,
                     cbet=0.25, semibluff=0.05, call_margin=0.18, fear=0.60, raise_value=0.95,
                     raise_bluff=0.0, bet_size=0.4),
    'Terrified': Params(open=0.06, steal_mult=1.1, limp=0.20, call_open=0.05, bb_defend=1.0,
                        threebet=0.01, call_3bet=0.015, fourbet=0.01, value=0.88, bluff=0.0,
                        cbet=0.10, semibluff=0.0, call_margin=0.25, fear=1.0, raise_value=0.97,
                        raise_bluff=0.0, bet_size=0.33),
}
SCARED_LEVELS = ['Nervous', 'Scared', 'Terrified']

# Ante-aware baseline for ante == big blind games (9bb of dead money at 7-max):
# wider positional opens, bigger opens and isolation raises, no limping,
# pot-odds blind defence, more 3-bets, smaller c-bets to pick up dead money.
PRESETS['AnteTAG'] = Params(
    open=0.16, pos_spread=1.6, steal_mult=1.25, limp=0.0, call_open=0.12, bb_defend=3.5,
    threebet=0.08, call_3bet=0.12, fourbet=0.04, open_size=3.0, iso=1.6, iso_per_limper=1.5,
    value=0.62, bluff=0.10, cbet=0.60, semibluff=0.5, call_margin=0.10, fear=0.0,
    raise_value=0.84, raise_bluff=0.03, bet_size=0.55)

# Wizard: AnteTAG plus "smart" mode - solved push/fold charts when short, and every
# postflop decision made on equity against each opponent's estimated range, with card
# removal (it knows nobody else can hold the cards it can see). Thresholds are lower
# than AnteTAG's because real equity against a range runs below the old heuristic.
PRESETS['Wizard'] = replace(PRESETS['AnteTAG'], smart=True, value=0.58, call_margin=0.03,
                            raise_value=0.80, semibluff=0.5, bluff=0.10)

# AnteTAG's parameters tuned for win rate by sim/tune.py against the rule-bot zoo
# (fish, passive and regs tables). It became a preflop maniac (VPIP ~74, PFR ~59,
# 3-bet ~22%, steals every time) that gives up postflop. It crushes opponents that
# over-fold to raises and never adapt, but its edge mostly disappears against
# adaptive ExploitBots - prefer AnteTAG unless you know opponents don't adjust.
PRESETS['AnteMax'] = Params(
    open=0.533, pos_spread=3.0, steal_mult=1.192, limp=0.0, call_open=0.284, bb_defend=2.277,
    threebet=0.224, call_3bet=0.106, fourbet=0.072, open_size=2.921, iso=1.664,
    iso_per_limper=0.951, value=0.499, bluff=0.175, cbet=0.215, semibluff=0.48,
    call_margin=0.126, fear=0.501, raise_value=0.746, raise_bluff=0.004, bet_size=0.622)


class Bot:

    def __init__(self, name, seed=0):
        self.name = name
        self.rng = random.Random(seed)

    def new_hand(self, hand_id):
        pass

    def act(self, st):
        raise NotImplementedError

    def end_hand(self, h):
        pass


class ParamBot(Bot):
    '''A rules bot driven entirely by a Params set.'''

    def __init__(self, name, params, seed=0):
        super().__init__(name, seed)
        self.p = params

    # hooks the ExploitBot overrides
    def params_for(self, st):
        return self.p

    def bluff_size(self, st, p):
        return p.bet_size

    def value_size(self, st, p):
        return p.bet_size

    def hand_strength(self, st, p):
        '''(strength, multiway-adjusted strength) for postflop decisions.'''
        if p.smart:
            if getattr(self, '_ranges', None) is None:
                self._ranges = RangeTracker(getattr(self, 'tracker', None))
            dead = list(st.hole) + list(st.board)
            opp = [self._ranges.range_for(st, i, dead) for i in st.active_seats if i != st.seat]
            eq = equity(st.hole, st.board, opp, samples=p.eq_samples, rng=self.rng)
            n = max(1, len(opp))
            s = eq ** (1.0 / n) if n > 1 else eq      # heads-up equivalent, so thresholds still apply
            self.last_equity = eq
            return s, s
        s = postflop_strength(st.hole, st.board)
        return s, s - 0.06 * (st.n_active - 2)      # be more careful multiway

    def act(self, st):
        p = self.params_for(st)
        if st.street == PREFLOP:
            return self._preflop(st, p)
        return self._postflop(st, p)

    # ---------------------------------------------------------------- preflop
    def _preflop(self, st, p):
        top = 1.0 - preflop_strength(st.hole)        # 0 = AA, 1 = 72o
        bb = st.big_blind
        r = st.raises_this_street
        voluntary = [a for a in st.street_actions if a.kind in (CALL, RAISE)]
        passive = Action(CHECK) if st.to_call == 0 else Action(FOLD)

        if p.smart:
            # short stacks: solved push/fold charts
            if r == 1 and not voluntary and pushfold.effective_stack(st) <= 15 * bb:
                shove = pushfold.first_in_shove(st)
                if shove is not None:
                    return Action(RAISE, st.max_raise_to) if shove else passive
            if r == 2 and pushfold.effective_stack(st) <= 25 * bb:
                call = pushfold.call_shove(st)
                if call is not None:
                    return Action(CALL) if call else passive

        if r == 1:
            limpers = sum(a.kind == CALL for a in voluntary)
            rng = p.open * (1 + p.pos_spread * POS_RANK.get(st.position, 0.0))
            if limpers:
                rng *= p.iso if st.position not in BLINDS else 1.0
            elif st.position in LATE:
                rng *= p.steal_mult
            if top <= rng:
                # size off the straddle when there is one
                unit = max(bb, st.current_bet)
                return Action(RAISE, int(unit * (p.open_size + p.iso_per_limper * limpers)))
            if top <= rng + p.limp:
                return Action(CALL)
            return passive
        if r == 2:
            callers = sum(a.kind == CALL for a in voluntary)
            raise_bb = st.current_bet / bb
            size_adj = min(1.0, 3.0 / max(raise_bb, 1.0))       # tighten vs big opens
            call_rng = p.call_open * size_adj * (p.bb_defend if st.position == 'BB' else 1.0)
            if top <= p.threebet:
                return Action(RAISE, int(st.current_bet * 3 + st.current_bet * callers))
            if top <= p.threebet + call_rng:
                return Action(CALL)
            return passive
        if r == 3:
            if top <= p.fourbet:
                return Action(RAISE, int(st.current_bet * 2.3))
            if top <= p.call_3bet:
                return Action(CALL)
            return passive
        # 4-bet or more: shove the very top, call a little more
        if top <= p.fourbet * 0.6:
            return Action(RAISE, st.max_raise_to)
        if top <= p.fourbet:
            return Action(CALL)
        return passive

    # --------------------------------------------------------------- postflop
    def _postflop(self, st, p):
        s, s_adj = self.hand_strength(st, p)
        pot = st.pot
        is_pfa = st.preflop_aggressor == st.seat

        if st.to_call == 0:
            if s_adj >= p.value:
                return self._bet(st, self.value_size(st, p))
            if is_pfa and st.street == FLOP and self.rng.random() < p.cbet:
                return self._bet(st, self.bluff_size(st, p) if s_adj < p.value else p.bet_size)
            if 0.3 <= s < p.value and self.rng.random() < p.semibluff * 0.5:
                return self._bet(st, p.bet_size)
            if s < 0.3 and self.rng.random() < p.bluff:
                return self._bet(st, self.bluff_size(st, p))
            return Action(CHECK)

        pot_odds = st.to_call / (pot + st.to_call)
        bet_frac = st.to_call / max(1, pot - st.to_call)
        need = pot_odds + p.call_margin + p.fear * min(bet_frac, 2.0) * 0.25
        if st.can_raise and s_adj >= p.raise_value:
            return Action(RAISE, int(st.current_bet * 3 + (pot - st.current_bet) * 0.5))
        if s_adj >= need:
            return Action(CALL)
        if st.can_raise and s < 0.35 and self.rng.random() < p.raise_bluff:
            return Action(RAISE, int(st.current_bet * 3))
        return Action(FOLD)

    def _bet(self, st, frac):
        return Action(BET, max(st.big_blind, int(st.pot * frac)))


class ExploitBot(ParamBot):
    '''
    TAG baseline that bends its strategy toward opponents' observed leaks.

    Each adjustment is blended in by confidence n / (n + k) for the stat it
    relies on, and estimates are shrunk toward a population prior, so the bot
    plays like the baseline until it has evidence.
    '''

    # adjustment groups, individually switchable for ablation tests
    GROUPS = ('steal', 'threebet', 'vs3bet', 'bluff', 'value', 'call', 'sizing')

    def __init__(self, name, params=PRESETS['TAG'], seed=0, k_conf=30, strength=1.0, disabled=(),
                 pool_mode=False):
        super().__init__(name, params, seed)
        self.tracker = StatsTracker()
        self.k = k_conf
        self.strength = strength   # 0 = pure baseline, 1 = full exploitation
        self.disabled = set(disabled)
        # pool_mode: opponents are anonymous (names change every hand), so model them
        # all as one "Pool" player, which is all an anonymous table allows
        self.pool_mode = pool_mode

    def end_hand(self, h):
        if self.pool_mode:
            h = replace(h, names=[nm if nm == self.name else 'Pool' for nm in h.names])
        self.tracker.update(h)

    def _opp(self, st, seat):
        return self.tracker.get('Pool' if self.pool_mode and st.names[seat] != self.name
                                else st.names[seat])

    def _others(self, st):
        return [self._opp(st, i) for i in st.active_seats if i != st.seat]

    def _blend(self, base, target, conf):
        a = conf * self.strength
        return base + a * (target - base)

    def _fold_prob(self, st, frac):
        '''Chance everyone still in folds to a bet of `frac` pot (multiway = product).'''
        key = 'fvb_small' if frac < 0.5 else 'fvb_big'
        prob = 1.0
        for o in self._others(st):
            f = o.rate(key, k=20)
            if st.street == FLOP and st.preflop_aggressor == st.seat:
                f = 0.5 * f + 0.5 * o.rate('fold_cbet', k=20)
            prob *= f
        return prob

    def _conf(self, st, key):
        others = self._others(st)
        return min((o.confidence(key, self.k) for o in others), default=0.0)

    def bluff_size(self, st, p):
        if 'sizing' in self.disabled:
            return p.bet_size
        # choose the size that maximises bluff EV given observed folds by size
        best, best_ev = p.bet_size, None
        for frac in (0.33, 0.66, 1.0):
            f = self._fold_prob(st, frac)
            ev = f * 1.0 - (1 - f) * frac
            if best_ev is None or ev > best_ev:
                best, best_ev = frac, ev
        return self._blend(p.bet_size, best, self._conf(st, 'fvb'))

    def value_size(self, st, p):
        if 'sizing' in self.disabled:
            return p.bet_size
        # bet bigger into players who call too much, smaller into players who fold a lot
        fvb = sum(o.rate('fvb', k=20) for o in self._others(st)) / max(1, len(self._others(st)))
        target = 1.0 if fvb < 0.30 else (0.5 if fvb > 0.60 else p.bet_size)
        return self._blend(p.bet_size, target, self._conf(st, 'fvb'))

    def params_for(self, st):
        p = self.p
        others = self._others(st)
        if not others:
            return p
        changes = {}

        if st.street == PREFLOP:
            if st.raises_this_street == 1 and st.position in LATE:
                # widen steals against blinds that give up too often
                blinds = [self._opp(st, i) for i, pos in enumerate(st.positions)
                          if pos in ('SB', 'BB') and i != st.seat]
                if blinds:
                    fts = min(b.rate('fold_steal', k=20) for b in blinds)
                    conf = min(b.confidence('fold_steal', self.k) for b in blinds)
                    # only ever widen: vs sticky blinds the baseline range is still a fine value range
                    target = min(3.5, max(p.steal_mult, p.steal_mult * (1 + 2.0 * (fts - 0.65))))
                    changes['steal_mult'] = self._blend(p.steal_mult, target, conf)
            if st.raises_this_street == 2:
                opener = self._raiser(st)
                if opener is not None:
                    o = self._opp(st, opener)
                    f3b = o.rate('fold_3bet', k=20)
                    pfr = o.rate('pfr', k=20)
                    width = min(2.5, max(0.4, pfr / 0.18))   # loose openers have weak ranges
                    # 3-bet wider for value vs loose openers and as a bluff vs over-folders
                    target = min(0.30, max(0.02, p.threebet * width + 0.4 * (f3b - 0.55)))
                    conf = min(o.confidence('fold_3bet', self.k), o.confidence('pfr', self.k)) \
                        if f3b > 0.55 else o.confidence('pfr', self.k)
                    changes['threebet'] = self._blend(p.threebet, target, conf)
                    # flat less against tight openers, more against loose ones
                    target = p.call_open * min(1.8, width)
                    changes['call_open'] = self._blend(p.call_open, target, o.confidence('pfr', self.k))
            if st.raises_this_street >= 3:
                raiser = self._raiser(st)
                if raiser is not None:
                    o = self._opp(st, raiser)
                    # a player who 3-bets a lot has a weak 3-betting range: continue wider
                    scale = min(4.0, max(0.5, o.rate('three_bet', k=20) / 0.07))
                    conf = o.confidence('three_bet', self.k)
                    changes['call_3bet'] = self._blend(p.call_3bet, min(0.4, p.call_3bet * scale), conf)
                    changes['fourbet'] = self._blend(p.fourbet, min(0.12, p.fourbet * min(scale, 3.0)), conf)
        else:
            # bluff more into folders, never into stations
            fold = self._fold_prob(st, 0.66)
            conf = self._conf(st, 'fvb')
            breakeven = 0.66 / 1.66
            bluff_target = min(0.95, max(0.0, (fold - breakeven) / 0.2))
            changes['bluff'] = self._blend(p.bluff, bluff_target, conf)
            changes['cbet'] = self._blend(p.cbet, min(1.0, max(0.2, (fold - breakeven) / 0.2 + 0.4)), conf)
            changes['semibluff'] = self._blend(p.semibluff, min(1.0, max(0.2, p.semibluff + (fold - 0.45))), conf)
            # value bet thinner against stations, thicker against folders
            fvb = sum(o.rate('fvb', k=20) for o in others) / len(others)
            changes['value'] = self._blend(p.value, p.value + 0.6 * (fvb - 0.45), conf)
            if st.to_call > 0:
                bettor = self._last_aggressor(st)
                if bettor is not None:
                    o = self._opp(st, bettor)
                    afq = o.rate('afq', k=20)
                    # passive players betting means strength; aggressive ones bluff more
                    target = p.call_margin + 0.6 * (0.40 - afq)
                    changes['call_margin'] = self._blend(p.call_margin, target, o.confidence('afq', self.k))
        drop = {'steal': ['steal_mult'], 'threebet': ['threebet', 'call_open'],
                'vs3bet': ['call_3bet', 'fourbet'], 'bluff': ['bluff', 'cbet', 'semibluff'],
                'value': ['value'], 'call': ['call_margin']}
        for g in self.disabled:
            for key in drop.get(g, []):
                changes.pop(key, None)
        return replace(p, **changes)

    @staticmethod
    def _raiser(st):
        for a in reversed(st.street_actions):
            if a.kind == RAISE:
                return a.seat
        return None

    @staticmethod
    def _last_aggressor(st):
        for a in reversed(st.street_actions):
            if a.kind in (BET, RAISE):
                return a.seat
        return None


def make_bot(kind, name=None, seed=0):
    '''Factory: 'Exploit', 'Exploit-<group>' (that adjustment group off), or any PRESETS key.'''
    name = name or kind
    if kind == 'Exploit':
        return ExploitBot(name, seed=seed)
    if kind == 'ExploitPool':
        return ExploitBot(name, seed=seed, pool_mode=True)
    if kind == 'Hunter':
        return Hunter(name, seed=seed)
    if kind == 'HunterPool':
        return Hunter(name, seed=seed, pool_mode=True)
    if kind.startswith('Hunter:'):            # Hunter on top of another preset, e.g. 'Hunter:LAG'
        return Hunter(name, params=PRESETS[kind.split(':', 1)[1]], seed=seed)
    if kind.startswith('Exploit-'):
        return ExploitBot(name, seed=seed, disabled=kind.split('-')[1:])
    return ParamBot(name, PRESETS[kind], seed=seed)


# ------------------------------------------------------------------------------ Hunter

def _wide_iso_hand(hole):
    '''"Any king, any ace, any two cards 7 or higher, and any pair" (Wilcox).'''
    r = sorted((RANK_VALUE[c[0]] for c in hole), reverse=True)
    return r[0] == r[1] or r[0] >= 13 or r[1] >= 7


def _value_iso_hand(hole):
    '''Against stations: "all aces, suited connectors and broadway hands" (plus pairs).'''
    r = sorted((RANK_VALUE[c[0]] for c in hole), reverse=True)
    suited = hole[0][1] == hole[1][1]
    return r[0] == r[1] or r[0] == 14 or r[1] >= 10 or (suited and r[0] - r[1] <= 2 and r[1] >= 4)


class Hunter(ExploitBot):
    '''
    Ante-aware baseline plus the "winning money from bad players" adjustments
    (Jack Wilcox, ThePokerBank), driven by the stats it collects:

    - Isolate limpers in position with a big raise. Against players who limp/fold
      or fold to c-bets, raise a wide range; against stations, only hands that make
      strong pairs/draws.
    - C-bet half pot with anything against players who fold to c-bets (>= 50%);
      against stations (fold to c-bet <= 30%) c-bet only made hands and give up otherwise.
    - After a flop c-bet is called, double-barrel only top pair or better.
    - Value bet stations three streets (2/3 pot), and thinly on the river (1/2 pot)
      when their WTSD is 35%+; with no read, check marginal rivers.
    - Passive players' check-raises are strong: fold all but overpair+.
    - Passive players' donk bets and tiny "blocking" bets are weak: raise / call wider.
    '''

    def __init__(self, name, params=None, seed=0, pool_mode=False):
        super().__init__(name, params or PRESETS['Wizard'], seed=seed, pool_mode=pool_mode)

    # keep the baseline sizing and params; reads are applied in act()
    def params_for(self, st):
        return self.p

    def bluff_size(self, st, p):
        return p.bet_size

    def value_size(self, st, p):
        return p.bet_size

    def _read(self, o):
        '''Classify an opponent: 'folder', 'station' or None (no clear read).'''
        fcb = o.rate('fold_cbet', k=10)
        lf = o.rate('limp_fold', k=10)
        wtsd = o.rate('wtsd', k=15)
        if fcb <= 0.30 or (wtsd >= 0.38 and fcb < 0.5):
            return 'station'
        if fcb >= 0.50 or lf >= 0.55:
            return 'folder'
        return None

    def _preflop(self, st, p):
        voluntary = [a for a in st.street_actions if a.kind in (CALL, RAISE)]
        limpers = [a.seat for a in voluntary if a.kind == CALL]
        if (st.raises_this_street == 1 and limpers and st.position not in BLINDS
                and not any(a.kind == RAISE for a in voluntary)):
            reads = {self._read(self._opp(st, i)) for i in limpers}
            base = super()._preflop(st, p)
            if base.kind == RAISE:
                return base
            if 'station' in reads:
                ok = _value_iso_hand(st.hole)
            elif reads == {'folder'}:
                ok = _wide_iso_hand(st.hole)
            else:
                ok = False
            if ok:
                unit = max(st.big_blind, st.current_bet)
                return Action(RAISE, int(unit * (p.open_size + p.iso_per_limper * len(limpers))))
            return base
        return super()._preflop(st, p)

    def _postflop(self, st, p):
        others = [i for i in st.active_seats if i != st.seat]
        if len(others) != 1:
            return super()._postflop(st, p)
        opp = self._opp(st, others[0])
        read = self._read(opp)
        passive = opp.rate('afq', k=20) < 0.30
        s, _ = self.hand_strength(st, p)
        pot = st.pot
        is_pfa = st.preflop_aggressor == st.seat
        prev = {FLOP: PREFLOP, 'turn': FLOP, 'river': 'turn'}[st.street]
        barreling = st.street != FLOP and self._we_bet_and_got_called(st, prev)

        if st.to_call == 0:
            if st.street == FLOP and is_pfa:
                if read == 'folder':
                    return self._bet(st, 0.5)                      # needs ~33% folds, they fold 50%+
                if read == 'station':
                    return self._bet(st, 0.66) if s >= p.value else Action(CHECK)
            if barreling:
                if read == 'station' and s >= 0.60:
                    return self._bet(st, 0.66)                     # value them three streets
                if st.street == 'river' and s >= 0.55 and opp.rate('wtsd', k=15) >= 0.35:
                    return self._bet(st, 0.5)                      # thin value vs showdown-happy
                return self._bet(st, 0.55) if s >= 0.66 else Action(CHECK)   # top pair+ only
            if read == 'station' and s < p.value:
                return Action(CHECK)                               # no bluffs into stations
            return super()._postflop(st, p)

        bettor_raised_us = any(a.seat == st.seat and a.kind in (BET, RAISE) for a in st.street_actions)
        bet_frac = st.to_call / max(1, pot - st.to_call)
        if bettor_raised_us and passive:
            return Action(CALL) if s >= 0.80 else Action(FOLD)     # passive check-raise = strong
        if st.street == FLOP and is_pfa and passive and not bettor_raised_us:
            # donk bet from a passive player: draws and weak pairs
            if st.can_raise and s >= 0.55:
                return Action(RAISE, int(st.current_bet * 3))
        if passive and bet_frac <= 0.35:
            # small "blocking" bet = weak showdown value
            if st.can_raise and s >= 0.72:
                return Action(RAISE, int(st.current_bet * 3 + (pot - st.current_bet) * 0.5))
            return Action(CALL) if s >= st.to_call / (pot + st.to_call) + p.call_margin - 0.08 \
                else super()._postflop(st, p)
        return super()._postflop(st, p)

    @staticmethod
    def _we_bet_and_got_called(st, street):
        acts = [a for a in st.history if a.street == street]
        ours = [k for k, a in enumerate(acts) if a.seat == st.seat and a.kind in (BET, RAISE)]
        return bool(ours) and any(a.kind == CALL for a in acts[ours[-1] + 1:])
