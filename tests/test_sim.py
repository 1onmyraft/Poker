import unittest

from sim.cards import evaluate, preflop_strength
from sim.engine import Table, Action, FOLD, CHECK, CALL, BET, RAISE
from sim.bots import Bot, make_bot, PRESETS
from sim.stats import StatsTracker
from sim.strength import postflop_strength
from sim.handhistory import parse_hands, replay, generate, write_hand
from sim.backtest import backtest, score
from sim.calibrate import target_from, distance


class Scripted(Bot):
    '''Plays a fixed list of actions; checks/folds when the script runs out.'''

    def __init__(self, name, script):
        super().__init__(name)
        self.script = list(script)
        self.seen = []

    def act(self, st):
        self.seen.append((st.street, st.position, st.to_call))
        if self.script:
            return self.script.pop(0)
        return Action(CHECK if st.to_call == 0 else FOLD)


class TestEvaluator(unittest.TestCase):

    def test_category_order(self):
        hands = [
            ['2c', '3d', '5h', '8s', 'Kd'],          # high card
            ['2c', '2d', '5h', '8s', 'Kd'],          # pair
            ['2c', '2d', '5h', '5s', 'Kd'],          # two pair
            ['2c', '2d', '2h', '8s', 'Kd'],          # trips
            ['Ac', '2d', '3h', '4s', '5d'],          # wheel
            ['6c', '2d', '3h', '4s', '5d'],          # six-high straight
            ['2c', '7c', '5c', '8c', 'Kc'],          # flush
            ['2c', '2d', '2h', '8s', '8d'],          # full house
            ['2c', '2d', '2h', '2s', 'Kd'],          # quads
            ['Ac', '2c', '3c', '4c', '5c'],          # steel wheel
        ]
        values = [evaluate(h) for h in hands]
        self.assertEqual(values, sorted(values))

    def test_seven_cards_and_kickers(self):
        self.assertGreater(evaluate(['Ah', 'Kd', 'Qs', 'Qc', '7d', '3h', '2s']),
                           evaluate(['Ah', 'Jd', 'Qs', 'Qc', '7d', '3h', '2s']))
        self.assertEqual(evaluate(['Ah', 'Kd', '9s', '9c', '9d', '9h', '2s'])[0], 7)

    def test_preflop_strength(self):
        self.assertGreater(preflop_strength(['Ah', 'Ad']), 0.99)
        self.assertLess(preflop_strength(['7h', '2d']), 0.01)
        self.assertGreater(preflop_strength(['Ah', 'Kh']), preflop_strength(['Ah', 'Kd']))

    def test_postflop_strength(self):
        board = ['Kh', '7d', '2c']
        self.assertGreater(postflop_strength(['7c', '7s'], board), postflop_strength(['Ks', 'Qd'], board))
        self.assertGreater(postflop_strength(['Ks', 'Qd'], board), postflop_strength(['8s', '8d'], board))
        self.assertGreater(postflop_strength(['8s', '8d'], board), postflop_strength(['Js', 'Td'], board))
        # flush draw adds equity on the flop but not on the river
        fd = postflop_strength(['Ah', '5h'], ['Kh', '7h', '2c'])
        self.assertGreater(fd, postflop_strength(['As', '5d'], ['Kh', '7h', '2c']))


class TestEngine(unittest.TestCase):

    def test_heads_up_order_and_blinds(self):
        btn = Scripted('btn', [Action(CALL)])
        bb = Scripted('bb', [Action(CHECK)])
        h = Table(big_blind=2).play_hand([btn, bb], deck_seed=1)
        self.assertEqual(btn.seen[0], ('preflop', 'BTN', 1))  # button is SB and acts first preflop
        self.assertEqual(bb.seen[1][0], 'flop')
        self.assertEqual(h.actions[2].seat, 1)                 # BB acts first postflop
        self.assertEqual(sum(h.winnings), 0)

    def test_fold_wins_blinds(self):
        h = Table(big_blind=2).play_hand([Scripted('a', [Action(FOLD)]), Scripted('b', [])], deck_seed=3)
        self.assertEqual(h.winnings, [-1, 1])
        self.assertEqual(h.showdown, [])

    def test_min_raise_is_enforced(self):
        a = Scripted('a', [Action(RAISE, 3)])  # below the min raise to 4
        b = Scripted('b', [Action(FOLD)])
        h = Table(big_blind=2).play_hand([a, b], deck_seed=3)
        self.assertEqual(h.actions[0].to, 4)

    def test_side_pots(self):
        # three-way all-in with different stacks; total must be conserved and
        # the short stack can only win the main pot
        for seed in range(50):
            bots = [Scripted('a', [Action(RAISE, 10 ** 6)]), Scripted('b', [Action(CALL)]),
                    Scripted('c', [Action(CALL)])]
            stacks = [50, 120, 200]
            h = Table(big_blind=2).play_hand(bots, deck_seed=seed, stacks=stacks)
            self.assertEqual(sum(h.winnings), 0)
            self.assertLessEqual(h.winnings[0], 100)        # max 50 from each opponent
            self.assertGreaterEqual(h.winnings[0], -50)
            self.assertEqual(len(h.board), 5)

    def test_allin_ev(self):
        # preflop all-in: EV is zero-sum and close to the actual result on average
        diffs = []
        for seed in range(40):
            bots = [Scripted('a', [Action(RAISE, 10 ** 6)]), Scripted('b', [Action(CALL)])]
            h = Table(big_blind=2).play_hand(bots, deck_seed=seed)
            self.assertIsNotNone(h.ev_winnings)
            self.assertAlmostEqual(sum(h.ev_winnings), 0, places=6)
            self.assertTrue(-200 <= h.ev_winnings[0] <= 200)
            diffs.append(h.winnings[0] - h.ev_winnings[0])
        # AA vs 72o style lopsided spots: EV must favour the hand with better cards
        self.assertLess(abs(sum(diffs) / len(diffs)), 100)

    def test_no_ev_without_allin(self):
        h = Table(big_blind=2).play_hand([Scripted('a', [Action(CALL)]), Scripted('b', [])], deck_seed=4)
        self.assertIsNone(h.ev_winnings)

    def test_zero_sum_with_zoo(self):
        table = Table()
        bots = [make_bot(k) for k in PRESETS] + [make_bot('Exploit')]
        for d in range(300):
            seats = bots[d % 6: d % 6 + 6] if d % 6 + 6 <= len(bots) else bots[:6]
            h = table.play_hand(seats, deck_seed=d, hand_id=d)
            self.assertEqual(sum(h.winnings), 0)


class TestStats(unittest.TestCase):

    def test_steal_cbet_fold(self):
        btn = Scripted('btn', [Action(RAISE, 5), Action(BET, 6)])
        bb = Scripted('bb', [Action(CALL), Action(CHECK), Action(FOLD)])
        h = Table(big_blind=2).play_hand([btn, bb], deck_seed=7)
        tr = StatsTracker()
        tr.update(h)
        b, g = tr.get('btn'), tr.get('bb')
        self.assertEqual((b.stats['vpip'].count, b.stats['pfr'].count, b.stats['steal'].count), (1, 1, 1))
        self.assertEqual((b.stats['cbet'].count, b.stats['cbet'].opp), (1, 1))
        self.assertEqual((g.stats['fold_steal'].count, g.stats['fold_steal'].opp), (0, 1))
        self.assertEqual((g.stats['three_bet'].count, g.stats['three_bet'].opp), (0, 1))
        self.assertEqual((g.stats['fold_cbet'].count, g.stats['fold_cbet'].opp), (1, 1))
        self.assertEqual((g.stats['wtsd'].count, g.stats['wtsd'].opp), (0, 1))
        self.assertEqual(b.stats['wwsf'].count, 1)

    def test_fold_to_3bet_and_shrinkage(self):
        a = Scripted('a', [Action(RAISE, 5), Action(FOLD)])
        b = Scripted('b', [Action(RAISE, 15)])
        tr = StatsTracker()
        tr.update(Table(big_blind=2).play_hand([a, b], deck_seed=2))
        pa = tr.get('a')
        self.assertEqual((pa.stats['fold_3bet'].count, pa.stats['fold_3bet'].opp), (1, 1))
        self.assertEqual(tr.get('b').stats['three_bet'].count, 1)
        # one observation barely moves the shrunk estimate off the prior
        self.assertLess(pa.rate('fold_3bet', k=20), 0.6)
        self.assertEqual(pa.rate('fold_3bet', shrink=False), 1.0)


SNIPPET = """1onmyraftpoker Hand #1: NLH (₮0.10/₮0.10/₮0.10) 2026/10/07 00:33:33 PDT
Table '1' 7-max Seat #3 is the button
Seat 1: aaaaaaaa (₮20 in chips)
Seat 3: bbbbbbbb (₮5 in chips)
Seat 4: cccccccc (₮8 in chips)
Seat 5: Hero (₮10 in chips)
Seat 6: dddddddd (₮12 in chips)
aaaaaaaa: posts ante ₮0.10
bbbbbbbb: posts ante ₮0.10
cccccccc: posts ante ₮0.10
Hero: posts ante ₮0.10
dddddddd: posts ante ₮0.10
cccccccc: posts small blind ₮0.10
Hero: posts big blind ₮0.10
aaaaaaaa: posts auto big blind ₮0.10
*** HOLE CARDS ***
Dealt to aaaaaaaa
Dealt to bbbbbbbb
Dealt to cccccccc
Dealt to Hero [Ah Kd]
Dealt to dddddddd
dddddddd: STRADDLE ₮0.20
aaaaaaaa: raises ₮0.40 to ₮0.60
bbbbbbbb: folds
cccccccc: folds
Hero: ALLIN ₮9.80
dddddddd: folds
aaaaaaaa: calls ₮9.30
*** FLOP *** [2c 7d 9h]
*** TURN *** [2c 7d 9h] [Js]
*** RIVER *** [2c 7d 9h Js] [3s]
*** SHOWDOWN ***
aaaaaaaa: shows [Qs Qd] (One Pair)
aaaaaaaa collected ₮19.57 from pot
Hero cashed out the hand for ₮6 | Cash Out Fee ₮0.20
Hero: shows [Ah Kd] (High Card)
*** SUMMARY ***
Total pot ₮20.60 | Rake ₮1.03
Hand was run once
Board [ 2c 7d 9h Js 3s ]
Game ended: 2026/10/07 00:34:33 PDT
Seat 1: aaaaaaaa showed [Qs Qd] and won (₮19.57) with One Pair
Seat 3: bbbbbbbb folded before Flop (didn't bet)
Seat 4: cccccccc folded before Flop (didn't bet)
Seat 5: Hero showed [Ah Kd] and cashed out for ₮6 | Cash Out Fee ₮0.20
Seat 6: dddddddd folded before Flop (didn't bet)
"""


class TestHandHistory(unittest.TestCase):

    def test_parse_snippet(self):
        (ph,) = parse_hands(SNIPPET)
        self.assertEqual((ph.sb, ph.bb, ph.ante, ph.button_seat), (10, 10, 10, 3))
        self.assertEqual(ph.hero_cards, ['Ah', 'Kd'])
        self.assertEqual(sum(ph.invested().values()), ph.total_pot)
        self.assertEqual(ph.net('Hero'), 600 - 1000)              # cash-out counts
        self.assertEqual(ph.net('aaaaaaaa'), 1957 - 1000)
        h, decisions = replay(ph, candidates=[make_bot('TAG')])
        self.assertEqual(len(decisions), 1)                        # Hero's single decision
        st, hero, picks = decisions[0]
        self.assertEqual((st.position, st.to_call, hero.kind), ('BB', 50, RAISE))
        self.assertEqual(sum(h.invested), 2060)

    def test_round_trip(self):
        bots = [make_bot(k, k, seed=i) for i, k in enumerate(
            ['TAG', 'LAG', 'Nit', 'Station', 'Maniac', 'Scared', 'Nervous'])]
        text, hist = generate(bots, 150, seed=11, straddle_rate=0.3)
        hands = parse_hands(text)
        self.assertEqual(len(hands), 150)
        for ph, (h, order) in zip(hands, hist):
            replay(ph)                                            # raises on any mismatch
            self.assertEqual(sum(ph.invested().values()), sum(h.invested))
            self.assertEqual(ph.rake, h.rake)
            names = [ph.seats[i + 1][0] for i in order]
            for j, nm in enumerate(names):
                self.assertEqual(ph.net(nm), h.winnings[j])
            self.assertEqual(sum(h.winnings), -h.rake)

    def test_backtest_agrees_with_itself(self):
        bots = [make_bot(k, k, seed=i) for i, k in enumerate(
            ['TAG', 'Nervous', 'Scared', 'Station', 'Maniac', 'LAG', 'Nit'])]
        text, _ = generate(bots, 200, seed=5, hero_index=0)
        _, rows, _, skipped = backtest(parse_hands(text), ['TAG', 'Nit'])
        self.assertEqual(skipped, [])
        s = score(rows, 'TAG')
        self.assertEqual(s['agree']['preflop'], s['total']['preflop'])   # deterministic preflop
        n = score(rows, 'Nit')
        self.assertLess(n['agree']['preflop'], n['total']['preflop'])


class TestCalibrate(unittest.TestCase):

    def test_distance_is_zero_on_itself_and_grows(self):
        tr = StatsTracker()
        table = Table()
        bots = [make_bot('Scared', 'a'), make_bot('Maniac', 'b')]
        for d in range(400):
            tr.update(table.play_hand(bots if d % 2 else bots[::-1], deck_seed=d))
        t = target_from(tr.get('a'))
        self.assertIn('vpip', t)
        self.assertAlmostEqual(distance(tr.get('a'), t), 0.0)
        self.assertGreater(distance(tr.get('b'), t), 50)


if __name__ == '__main__':
    unittest.main()
