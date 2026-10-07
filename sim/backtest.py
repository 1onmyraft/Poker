'''
Backtest bots against a hand-history file.

Every hand is replayed through the engine; at each of Hero's decisions every
candidate bot is asked what it would do in exactly that spot. Two things are
reported per bot:

1. Agreement: how often the bot picks the same action type as Hero.
2. Counterfactual result, only where it can be known exactly:
   - the bot takes Hero's line all the way      -> same result as Hero
   - the bot folds at the first point it differs -> it loses only what was in so far
   Hands where the bot would have *continued differently* (called where Hero folded,
   raised where Hero called, ...) can't be scored without knowing how opponents
   would respond, so they are counted as unresolved rather than guessed.

    python -m sim.backtest HISTORY.txt [--bots TAG,Nit,Scared] [--out report.md]
'''
import argparse
import math
from collections import Counter, defaultdict

from .bots import make_bot, PRESETS
from .engine import PREFLOP, FLOP, TURN, RIVER, FOLD, BET, RAISE
from .handhistory import parse_file, replay, ReplayError, money
from .stats import StatsTracker, STAT_INFO

STREETS = [PREFLOP, FLOP, TURN, RIVER]
DEFAULT_BOTS = ['TAG', 'LAG', 'Nit', 'Nervous', 'Scared', 'Terrified', 'Station', 'Maniac']


def _kind(a):
    return a.kind


def backtest(hands, bot_kinds=DEFAULT_BOTS, seed=0):
    bots = [make_bot(k, k, seed=seed + i) for i, k in enumerate(bot_kinds)]
    tracker = StatsTracker()
    skipped = []
    rows = []      # per replayed hand
    for ph in hands:
        if not ph.hero:
            skipped.append((ph.hand_id, 'no hero'))
            continue
        try:
            h, decisions = replay(ph, candidates=bots, seed=seed)
        except ReplayError as e:
            skipped.append((ph.hand_id, str(e)))
            continue
        tracker.update(h)
        hero_seat = h.names.index(ph.hero)
        start = h.start_stacks[hero_seat]
        rows.append({'ph': ph, 'decisions': decisions, 'start': start,
                     'hero_net': ph.net(ph.hero), 'bb': ph.bb})
    return bots, rows, tracker, skipped


def score(rows, bot_name):
    agree = Counter()
    total = Counter()
    sizing = 0
    resolved = []      # (hand row, bot_net, how)
    unresolved = Counter()
    unresolved_hero_net = 0
    plays = 0          # hands where the bot voluntarily continues preflop when Hero did
    for r in rows:
        first_div = None
        for st, hero, picks in r['decisions']:
            bot = picks[bot_name]
            total[st.street] += 1
            if bot.kind == hero.kind:
                agree[st.street] += 1
                if bot.kind in (BET, RAISE) and abs(bot.amount - hero.amount) > max(st.big_blind, 0.25 * hero.amount):
                    sizing += 1
            elif first_div is None:
                first_div = (st, hero, bot)
        if first_div is None:
            resolved.append((r, r['hero_net'], 'same line'))
            continue
        st, hero, bot = first_div
        if bot.kind == FOLD:
            resolved.append((r, -(r['start'] - st.stack), 'folds earlier'))
        else:
            how = 'continues where Hero folded' if hero.kind == FOLD else 'different line'
            unresolved[how] += 1
            unresolved_hero_net += r['hero_net']
    return {'agree': agree, 'total': total, 'sizing': sizing, 'resolved': resolved,
            'unresolved': unresolved, 'unresolved_hero_net': unresolved_hero_net}


def _ci(diffs):
    n = len(diffs)
    if n < 2:
        return float('nan')
    m = sum(diffs) / n
    sd = math.sqrt(sum((d - m) ** 2 for d in diffs) / (n - 1))
    return 1.96 * sd * math.sqrt(n)    # CI on the *sum*


def report(path, bot_kinds=DEFAULT_BOTS):
    hands = parse_file(path)
    bots, rows, tracker, skipped = backtest(hands, bot_kinds)
    bb = rows[0]['bb'] if rows else 10
    hero_total = sum(r['hero_net'] for r in rows)
    n_dec = sum(len(r['decisions']) for r in rows)

    L = ['# Backtest: %s' % path.split('/')[-1], '',
         '- Hands in file: **%d**; replayed exactly through the engine: **%d**%s' % (
             len(hands), len(rows), (' (skipped: %s)' % '; '.join('#%s %s' % s for s in skipped)) if skipped else ''),
         '- Hero decisions examined: **%d**' % n_dec,
         '- Hero result: **%s** (%+.1f bb, %+.0f bb/100) - includes cash-outs, after rake' % (
             money(hero_total) if hero_total >= 0 else '-' + money(-hero_total), hero_total / bb,
             100 * hero_total / bb / max(1, len(rows))),
         '']

    # Hero's own tendencies
    p = tracker.get(rows[0]['ph'].hero) if rows else None
    if p:
        keys = ['vpip', 'pfr', 'limp', 'three_bet', 'steal', 'cbet', 'fold_cbet', 'fvb', 'afq', 'wtsd', 'wsd']
        L += ['## Hero tendencies over these hands', '',
              '| ' + ' | '.join(STAT_INFO[k][0] for k in keys) + ' | AF |',
              '|' + '---:|' * (len(keys) + 1),
              '| ' + ' | '.join(_pct(p, k) for k in keys) + ' | %.2f |' % p.af(), '',
              '(sample counts: ' + ', '.join('%s %d/%d' % (STAT_INFO[k][0], p.stats[k].count, p.stats[k].opp)
                                            for k in keys) + ')', '']

    # per-bot summary
    L += ['## Bots vs Hero', '',
          'Agreement = same action type as Hero at the same decision. The counterfactual '
          'compares Hero and the bot only on hands whose outcome for the bot is known exactly.', '',
          '| Bot | Agree (all) | Preflop | Flop | Turn | River | Scored hands | Hero on scored | Bot on scored | Bot − Hero | Unscored |',
          '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    scores = {}
    for b in bots:
        s = scores[b.name] = score(rows, b.name)
        tot = sum(s['total'].values())
        ag = sum(s['agree'].values())
        cells = ['%.0f%%' % (100 * ag / tot) if tot else '-']
        for stt in STREETS:
            cells.append('%.0f%% (%d)' % (100 * s['agree'][stt] / s['total'][stt], s['total'][stt])
                         if s['total'][stt] else '-')
        hero_sc = sum(r['hero_net'] for r, _, _ in s['resolved'])
        bot_sc = sum(net for _, net, _ in s['resolved'])
        diffs = [net - r['hero_net'] for r, net, _ in s['resolved']]
        L.append('| %s | %s | %d | %+.1f bb | %+.1f bb | **%+.1f ± %.0f bb** | %d |' % (
            b.name, ' | '.join(cells), len(s['resolved']), hero_sc / bb, bot_sc / bb,
            (bot_sc - hero_sc) / bb, _ci(diffs) / bb, sum(s['unresolved'].values())))
    L += ['', '± is a 95% interval on the total difference. Unscored hands are ones where the bot '
          'would have played on differently from Hero, so its result can\'t be known from the log.', '']

    # where Hero and the field disagree most
    L += ['## Spots where most bots disagree with Hero', '',
          '| Hand | Street | Hero cards | Board | Facing | Hero | Bots (TAG / Nit / LAG) | Hero net |',
          '|---|---|---|---|---:|---|---|---:|']
    spots = []
    for r in rows:
        for st, hero, picks in r['decisions']:
            dis = sum(1 for a in picks.values() if a.kind != hero.kind)
            if dis >= len(picks) - 1:   # first spot per hand where (nearly) every bot differs
                spots.append((abs(r['hero_net']), r, st, hero, picks))
                break
    spots.sort(key=lambda x: -x[0])
    for _, r, st, hero, picks in spots[:15]:
        show = ' / '.join(_act(picks[k], bb) for k in ('TAG', 'Nit', 'LAG') if k in picks)
        L.append('| #%s | %s | %s | %s | %s | %s | %s | %+.1f bb |' % (
            r['ph'].hand_id[-4:], st.street, ' '.join(st.hole), ' '.join(st.board) or '-',
            '%.1f bb' % (st.to_call / bb), _act(hero, bb), show, r['hero_net'] / bb))
    L += ['']

    # unresolved breakdown
    L += ['## Why hands were unscored', '', '| Bot | ' + ' | '.join(['continues where Hero folded', 'different line']) + ' |',
          '|---|---:|---:|']
    for b in bots:
        u = scores[b.name]['unresolved']
        L.append('| %s | %d | %d |' % (b.name, u['continues where Hero folded'], u['different line']))
    L += ['', '## How much to trust this', '',
          'This is %d hands. In a 10bb-ante/blind game the swing per hand is large: a single '
          'stacked all-in is ~100 bb, so the intervals above are wide, and a bot "beating" Hero '
          'here mostly means it folded before a few big losing pots. Use it to find spots to '
          'study, then confirm with the simulator over 100k+ hands.' % len(rows), '']
    return '\n'.join(L)


def _pct(p, k):
    r = p.rate(k, shrink=False)
    return '-' if r != r else '%.0f' % (100 * r)


def _act(a, bb):
    if a.kind in (BET, RAISE):
        return '%s %.1f bb' % (a.kind, a.amount / bb)
    return a.kind


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('history')
    ap.add_argument('--bots', default=','.join(DEFAULT_BOTS))
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    kinds = [k.strip() for k in a.bots.split(',')]
    for k in kinds:
        if k not in PRESETS:
            ap.error('unknown bot %s (choose from %s)' % (k, ', '.join(PRESETS)))
    text = report(a.history, kinds)
    if a.out:
        with open(a.out, 'w') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
