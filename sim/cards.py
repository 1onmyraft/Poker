'''
Cards, a fast 7-card evaluator, and preflop hand ranking.

Cards use the same 2-char format as the rest of the game, e.g. 'As', 'Td'.
Kept free of GUI/numpy imports so the simulator runs headless and fast.
'''
from collections import Counter
from itertools import combinations

RANKS = '23456789TJQKA'
SUITS = 'shcd'
RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}
DECK = [r + s for r in RANKS for s in SUITS]

# Hand categories (higher is better)
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY_NAMES = ['high card', 'one pair', 'two pairs', 'three of a kind', 'straight',
                  'flush', 'full house', 'four of a kind', 'straight flush']


# (top card, bitmask of the five ranks) for every straight, best first; the ace also plays low
_STRAIGHTS = [(top, sum(1 << (top - k) for k in range(5))) for top in range(14, 4, -1)]


def _straight_high(rank_set):
    """Highest straight top card in a set of rank values, or 0."""
    m = 0
    for r in rank_set:
        m |= 1 << r
    if m & (1 << 14):
        m |= 2                      # ace counts as 1 for the wheel
    for top, mask in _STRAIGHTS:
        if m & mask == mask:
            return top
    return 0


def evaluate(cards):
    '''
    PARAMETERS:
        cards: list of 5-7 card strings

    RETURN: tuple, comparable; larger is better. First element is the category.
    '''
    rks = [RANK_VALUE[c[0]] for c in cards]
    suit_count = Counter(c[1] for c in cards)
    flush_suit, n = suit_count.most_common(1)[0]
    if n >= 5:
        f_ranks = sorted((RANK_VALUE[c[0]] for c in cards if c[1] == flush_suit), reverse=True)
        sf = _straight_high(set(f_ranks))
        if sf:
            return (STRAIGHT_FLUSH, sf)
    counts = Counter(rks)
    # sort ranks by (count, rank) descending
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in rks if r != quad)
        return (QUADS, quad, kicker)
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (FULL_HOUSE, groups[0][0], groups[1][0])
    if n >= 5:
        return (FLUSH,) + tuple(f_ranks[:5])
    st = _straight_high(set(rks))
    if st:
        return (STRAIGHT, st)
    if groups[0][1] == 3:
        trips = groups[0][0]
        kick = sorted((r for r in rks if r != trips), reverse=True)[:2]
        return (TRIPS, trips) + tuple(kick)
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hi, lo = groups[0][0], groups[1][0]
        kicker = max(r for r in rks if r != hi and r != lo)
        return (TWO_PAIR, hi, lo, kicker)
    if groups[0][1] == 2:
        pair = groups[0][0]
        kick = sorted((r for r in rks if r != pair), reverse=True)[:3]
        return (PAIR, pair) + tuple(kick)
    return (HIGH_CARD,) + tuple(sorted(rks, reverse=True)[:5])


# Preflop ordering of the 169 starting hands, strongest first (same table as misc.pf_compact).
PF_ORDER = [
    'AA', 'KK', 'QQ', 'AKs', 'JJ', 'AQs', 'KQs', 'AJs', 'KJs', 'TT', 'AKo', 'ATs', 'QJs',
    'KTs', 'QTs', 'JTs', '99', 'AQo', 'A9s', 'KQo', '88', 'K9s', 'T9s', 'A8s', 'Q9s', 'J9s',
    'AJo', 'A5s', '77', 'A7s', 'KJo', 'A4s', 'A3s', 'A6s', 'QJo', '66', 'K8s', 'T8s', 'A2s',
    '98s', 'J8s', 'ATo', 'Q8s', 'K7s', 'KTo', '55', 'JTo', '87s', 'QTo', '44', '22', '33',
    'K6s', '97s', 'K5s', '76s', 'T7s', 'K4s', 'K2s', 'K3s', 'Q7s', '86s', '65s', 'J7s', '54s',
    'Q6s', '75s', '96s', 'Q5s', '64s', 'Q4s', 'Q3s', 'T9o', 'T6s', 'Q2s', 'A9o', '53s', '85s',
    'J6s', 'J9o', 'K9o', 'J5s', 'Q9o', '43s', '74s', 'J4s', 'J3s', '95s', 'J2s', '63s', 'A8o',
    '52s', 'T5s', '84s', 'T4s', 'T3s', '42s', 'T2s', '98o', 'T8o', 'A5o', 'A7o', '73s', 'A4o',
    '32s', '94s', '93s', 'J8o', 'A3o', '62s', '92s', 'K8o', 'A6o', '87o', 'Q8o', '83s', 'A2o',
    '82s', '97o', '72s', '76o', 'K7o', '65o', 'T7o', 'K6o', '86o', '54o', 'K5o', 'J7o', '75o',
    'Q7o', 'K4o', 'K3o', '96o', 'K2o', '64o', 'Q6o', '53o', '85o', 'T6o', 'Q5o', '43o', 'Q4o',
    'Q3o', '74o', 'Q2o', 'J6o', '63o', 'J5o', '95o', '52o', 'J4o', 'J3o', '42o', 'J2o', '84o',
    'T5o', 'T4o', '32o', 'T3o', '73o', 'T2o', '62o', '94o', '93o', '92o', '83o', '82o', '72o',
]


def _combos(code):
    return 6 if len(code) == 2 else (4 if code[2] == 's' else 12)


# Fraction of all 1326 combos that are at least as strong as each hand (0 = best, 1 = worst).
PF_PERCENTILE = {}
_acc = 0
for _code in PF_ORDER:
    _acc += _combos(_code)
    PF_PERCENTILE[_code] = _acc / 1326


def hand_code(hole):
    '''['Ah', 'Kh'] -> 'AKs'; ['7c', '7d'] -> '77'.'''
    a, b = hole
    ra, rb = a[0], b[0]
    if RANK_VALUE[ra] < RANK_VALUE[rb]:
        ra, rb = rb, ra
    if ra == rb:
        return ra + rb
    return ra + rb + ('s' if a[1] == b[1] else 'o')


def preflop_strength(hole):
    '''1.0 for AA down to ~0 for 72o. A hand with strength s is in the top (1 - s) of combos.'''
    return 1.0 - PF_PERCENTILE[hand_code(hole)]


def best_five(cards):
    '''Best 5-card subset (for display only; slow).'''
    return max(combinations(cards, 5), key=evaluate)


RANK_NAME = {2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine',
             10: 'Ten', 11: 'Jack', 12: 'Queen', 13: 'King', 14: 'Ace'}


def _plural(r):
    return 'Sixes' if r == 6 else RANK_NAME[r] + 's'


def describe(cards):
    '''Plain-English name of the best hand in 5-7 cards, e.g. "Two Pair, Kings and Fives".'''
    v = evaluate(cards)
    cat, r = v[0], v[1:]
    if cat == STRAIGHT_FLUSH:
        return 'Royal Flush' if r[0] == 14 else 'Straight Flush, %s-high' % RANK_NAME[r[0]]
    if cat == QUADS:
        return 'Four %s' % _plural(r[0])
    if cat == FULL_HOUSE:
        return 'Full House, %s full of %s' % (_plural(r[0]), _plural(r[1]))
    if cat == FLUSH:
        return 'Flush, %s-high' % RANK_NAME[r[0]]
    if cat == STRAIGHT:
        return 'Straight, %s-high' % RANK_NAME[r[0]]
    if cat == TRIPS:
        return 'Three %s' % _plural(r[0])
    if cat == TWO_PAIR:
        return 'Two Pair, %s and %s' % (_plural(r[0]), _plural(r[1]))
    if cat == PAIR:
        return 'Pair of %s' % _plural(r[0])
    return '%s-high' % RANK_NAME[r[0]]
