'''
Short-stack push/fold charts (solved offline by tools/solve_pushfold.py).

Reads resources/pushfold.json lazily; no numpy needed at runtime. Charts exist for
2-9 players, effective stacks 2-25 bb, and two structures: 'ante' (small blind =
big blind = ante) and 'classic' (half-blind small blind, no ante).
'''
import json
import os

from .cards import hand_code
from .engine import RAISE

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'pushfold.json')
_DATA = None
_CACHE = {}


def _data():
    global _DATA
    if _DATA is None:
        with open(PATH) as f:
            _DATA = json.load(f)
    return _DATA


def available():
    return os.path.exists(PATH)


def _hand_set(hexmask):
    if hexmask not in _CACHE:
        classes = _data()['classes_order']
        bits = int(hexmask, 16) if hexmask else 0
        _CACHE[hexmask] = {classes[h] for h in range(len(classes)) if bits >> h & 1}
    return _CACHE[hexmask]


def structure_of(st):
    ''''ante' or 'classic', from how much was posted before anyone acted.'''
    posted = st.pot - sum(a.added for a in st.history)
    return 'ante' if posted > 2.05 * st.big_blind else 'classic'


def _chart(st, depth_bb):
    depths = _data()['depths']
    d = min(depths, key=lambda x: abs(x - depth_bb))
    n = min(9, max(2, len(st.names)))
    return _data()['charts'].get('%s/%d/%d' % (structure_of(st), n, d))


def effective_stack(st):
    '''Our stack vs the biggest stack still to act behind us (chips incl. this street's bets).'''
    acted = {a.seat for a in st.street_actions}
    behind = [i for i in st.active_seats if i != st.seat and i not in acted]
    if not behind:
        behind = [i for i in st.active_seats if i != st.seat]
    mine = st.stack + st.committed
    theirs = max((st.stacks[i] + (st.street_bets[i] if st.street_bets else 0) for i in behind), default=mine)
    return min(mine, theirs)


def first_in_shove(st):
    '''True/False if the chart applies (unopened pot), else None.'''
    if not available():
        return None
    chart = _chart(st, effective_stack(st) / st.big_blind)
    if chart is None or st.position not in chart['push']:
        return None
    return hand_code(st.hole) in _hand_set(chart['push'][st.position])


def call_shove(st):
    '''Facing a single all-in shove and nothing else: True/False from the chart, else None.'''
    if not available():
        return None
    raises = [a for a in st.street_actions if a.kind == RAISE]
    if len(raises) != 1 or not raises[0].all_in:
        return None
    pusher = raises[0].seat
    depth = min(raises[0].to, st.stack + st.committed) / st.big_blind
    chart = _chart(st, depth)
    key = '%s<%s' % (st.position, st.positions[pusher])
    if chart is None or key not in chart['call']:
        return None
    return hand_code(st.hole) in _hand_set(chart['call'][key])
