'''
Cheap hand-strength estimates used by the bots.

Exact equity (Monte Carlo) is far too slow when simulating hundreds of
thousands of hands in pure Python, so postflop strength is a heuristic built
from the made-hand class (top pair, set, ...) plus draws. Values are rough
equity-vs-one-random-continuing-hand numbers so bots can compare them to pot odds.
'''
from collections import Counter

from .cards import (RANK_VALUE, evaluate, preflop_strength, PAIR, TWO_PAIR, TRIPS,
                    STRAIGHT, FLUSH, FULL_HOUSE)

__all__ = ['preflop_strength', 'postflop_strength']


def _draws(hole, board):
    '''Return (flush_draw, open_ender, gutshot) booleans for hands that use a hole card.'''
    cards = hole + board
    suit_count = Counter(c[1] for c in cards)
    flush_draw = any(n == 4 and any(h[1] == s for h in hole) for s, n in suit_count.items())

    ranks = {RANK_VALUE[c[0]] for c in cards}
    if 14 in ranks:
        ranks.add(1)
    hole_ranks = {RANK_VALUE[c[0]] for c in hole} | ({1} if any(c[0] == 'A' for c in hole) else set())
    # open-ender: 4 consecutive ranks with an open card on both ends (A234 and JQKA excluded)
    open_ender = any(
        set(range(low, low + 4)) <= ranks and set(range(low, low + 4)) & hole_ranks
        for low in range(2, 11))
    gutshot = not open_ender and any(
        len(set(range(low, low + 5)) & ranks) == 4 and set(range(low, low + 5)) & ranks & hole_ranks
        for low in range(1, 11))
    return flush_draw, open_ender, gutshot


def postflop_strength(hole, board):
    '''
    PARAMETERS:
        hole: list of 2 card strings
        board: list of 3-5 card strings

    RETURN: float in [0, 1], roughly equity vs one opponent
    '''
    mine = evaluate(hole + board)
    cat = mine[0]
    board_ranks = sorted({RANK_VALUE[c[0]] for c in board}, reverse=True)
    board_count = Counter(RANK_VALUE[c[0]] for c in board)
    h1, h2 = sorted((RANK_VALUE[c[0]] for c in hole), reverse=True)
    suits_on_board = Counter(c[1] for c in board).most_common(1)[0][1]
    board_plays = len(board) == 5 and evaluate(board) >= mine

    if board_plays:
        made = 0.12
    elif cat >= FULL_HOUSE:
        made = 0.97
    elif cat == FLUSH:
        top_hole = max((RANK_VALUE[c[0]] for c in hole if c[1] == _flush_suit(hole + board)), default=0)
        made = 0.95 if top_hole >= 13 else 0.88
    elif cat == STRAIGHT:
        made = 0.75 if suits_on_board >= 3 else 0.88
    elif cat == TRIPS:
        if h1 == h2:
            made = 0.92                     # set
        elif board_count.get(mine[1], 0) == 3:
            made = 0.15                     # trips on board
        else:
            made = 0.80                     # trips using a board pair
    elif cat == TWO_PAIR and h1 != h2 and h1 in board_count and h2 in board_count:
        made = 0.83                         # two pair using both hole cards
    elif cat in (PAIR, TWO_PAIR):
        made = _pair_strength(h1, h2, board_ranks)
        if cat == TWO_PAIR and made < 0.3:
            made = 0.2                      # board two pair, we only hold a kicker
    else:
        made = 0.25 if h1 == 14 else (0.18 if h1 >= 12 else 0.10)

    if suits_on_board >= 3 and cat < FLUSH and not board_plays:
        made *= 0.85                        # flush possible on board
    if len(board) == 5:
        return made

    flush_draw, open_ender, gutshot = _draws(hole, board)
    flop = len(board) == 3
    draw = 0.0
    if flush_draw and open_ender:
        draw = 0.52 if flop else 0.32
    elif flush_draw:
        draw = 0.35 if flop else 0.19
    elif open_ender:
        draw = 0.31 if flop else 0.17
    elif gutshot:
        draw = 0.16 if flop else 0.09
    return 1 - (1 - made) * (1 - draw)


def _flush_suit(cards):
    return Counter(c[1] for c in cards).most_common(1)[0][0]


def _pair_strength(h1, h2, board_ranks):
    top = board_ranks[0]
    if h1 == h2:
        if h1 > top:
            return 0.80 if h1 >= 11 else 0.72      # overpair
        if len(board_ranks) > 1 and h1 > board_ranks[1]:
            return 0.50                            # pocket pair below top card
        return 0.36
    for hole_rank, kicker in ((h1, h2), (h2, h1)):
        if hole_rank in board_ranks:
            idx = board_ranks.index(hole_rank)
            if idx == 0:
                return 0.72 if kicker >= 11 else (0.66 if kicker >= 9 else 0.60)
            if idx == 1:
                return 0.50
            return 0.40
    # pair is on the board; we have overcards at best
    return 0.22 if h1 == 14 else 0.14
