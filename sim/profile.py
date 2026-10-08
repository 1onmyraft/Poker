'''
Your player profile: everything the game can observe about how you play, kept
across sessions in history/profile.json (on your machine only; history/ is git-ignored).

What it records per hand: when it started/ended, your position, whether you played,
your result, and every decision you made with how long you took and how strong your
hand was at the time. On top of that it keeps the same stats/timing/tilt read the bots
build, so bots start each new session already knowing you.

`report()` turns it into plain-English findings: style, speed, timing tells, tilt,
session length, breaks (sitting out) and results by position.
'''
import json
import math
import os
import time

from .cards import preflop_strength
from .engine import PREFLOP, CALL, BET, RAISE
from .strength import postflop_strength

BREAK_SECONDS = 120          # a gap this long between hands counts as sitting out
VERSION = 1


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return float('nan')
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


class Profile:

    def __init__(self, path, name='You'):
        self.path = path
        self.name = name
        self.data = {'version': VERSION, 'name': name, 'read': None, 'sessions': []}
        if path and os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass                                   # unreadable: start fresh, keep the file aside
        self.session = None

    # ------------------------------------------------------------------ recording
    def start_session(self, structure, lineup):
        self.session = {'start': time.time(), 'end': None, 'structure': structure, 'lineup': list(lineup),
                        'hands': []}
        self.data['sessions'].append(self.session)

    def record_hand(self, h, hero_seat, t_start, t_end, tracker=None):
        '''Store one finished hand (engine HandHistory) from the hero's point of view.'''
        if self.session is None:
            return
        board_at = {'flop': 3, 'turn': 4, 'river': 5}
        hole = h.hole[hero_seat]
        decisions = []
        for a in h.actions:
            if a.seat != hero_seat:
                continue
            if a.street == PREFLOP:
                strength = preflop_strength(hole)
            else:
                strength = postflop_strength(list(hole), list(h.board[:board_at[a.street]]))
            decisions.append([a.street, a.kind, round(a.think_ms or 0), round(strength, 3),
                              round(a.to_call / h.big_blind, 1)])
        vpip = any(a.seat == hero_seat and a.street == PREFLOP and a.kind in (CALL, RAISE) for a in h.actions)
        self.session['hands'].append({
            't0': round(t_start - self.session['start'], 1), 't1': round(t_end - self.session['start'], 1),
            'pos': h.positions[hero_seat], 'net': round(h.winnings[hero_seat] / h.big_blind, 2),
            'vpip': vpip, 'showdown': hero_seat in h.showdown, 'decisions': decisions})
        self.session['end'] = t_end
        if tracker is not None:
            self.data['read'] = tracker.export_player(self.name)

    def end_session(self):
        if self.session is not None:
            self.session['end'] = self.session['end'] or time.time()
        self.save()

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, separators=(',', ':'))
        os.replace(tmp, self.path)

    def seed(self, tracker):
        '''Give a StatsTracker everything known about you from earlier sessions.'''
        if self.data.get('read'):
            tracker.import_player(self.name, self.data['read'])

    # ------------------------------------------------------------------- analysis
    def hands(self):
        return [hd for s in self.data['sessions'] for hd in s['hands']]

    def report(self):
        '''List of (heading, [lines]) with plain-English findings.'''
        sessions = [s for s in self.data['sessions'] if s['hands']]
        hands = self.hands()
        out = []
        if not hands:
            return [('Profile', ['No hands played yet. Play some and check back.'])]
        n = len(hands)
        net = sum(hd['net'] for hd in hands)
        secs = sum(s['hands'][-1]['t1'] for s in sessions)
        out.append(('Overview', [
            '%d session%s, %d hands, %s played.' % (len(sessions), '' if len(sessions) == 1 else 's', n, _dur(secs)),
            'Result: %+.1f bb (%+.1f bb per 100 hands). Hands per hour: %.0f.' % (
                net, 100 * net / n, n / max(secs / 3600, 1e-6)),
        ]))

        read = self.data.get('read') or {}
        st = read.get('stats', {})

        def pct(k):
            c, o = st.get(k, (0, 0))
            return '%d%%' % round(100 * c / o) if o else '-'
        out.append(('Style', [
            'You play %s of hands and raise %s before the flop; 3-bet %s; c-bet %s; fold to c-bets %s.' % (
                pct('vpip'), pct('pfr'), pct('three_bet'), pct('cbet'), pct('fold_cbet')),
            'You go to showdown %s of the time after the flop and win %s there.' % (pct('wtsd'), pct('wsd')),
        ]))

        # speed
        by_street = {}
        for hd in hands:
            for d in hd['decisions']:
                if d[2]:
                    by_street.setdefault(d[0], []).append(d[2] / 1000)
        if by_street:
            out.append(('Decision speed', [
                'Typical time to act: ' + ', '.join('%s %.1fs' % (s, _median(by_street[s]))
                                                    for s in ('preflop', 'flop', 'turn', 'river') if s in by_street) + '.',
            ] + self._fatigue(sessions)))

        out.append(('Timing tells (what your speed gives away)', self._tells(hands)))
        out.append(('Tilt', self._tilt(sessions)))
        out.append(('Session length', self._by_time(hands)))
        out.append(('Breaks (sitting out)', self._breaks(sessions)))
        out.append(('By position', self._positions(hands)))
        return out

    @staticmethod
    def _tells(hands):
        lines = []
        for label, kinds in (('bets/raises', (BET, RAISE)), ('calls', (CALL,))):
            pts = [(d[2], d[3]) for hd in hands for d in hd['decisions']
                   if d[1] in kinds and d[0] != 'preflop' and d[2]]
            if len(pts) < 12:
                lines.append('Not enough postflop %s yet (%d) to judge.' % (label, len(pts)))
                continue
            med = _median([p[0] for p in pts])
            fast = [s for t, s in pts if t <= med]
            slow = [s for t, s in pts if t > med]
            strong = lambda xs: 100.0 * sum(1 for s in xs if s >= 0.66) / max(1, len(xs))
            r = _corr([math.log(max(t, 1)) for t, _ in pts], [s for _, s in pts])
            verdict = ('fast = strong' if r < -0.15 else 'slow = strong' if r > 0.15 else 'no clear pattern')
            lines.append('Your %s: fast ones (<%.1fs) are strong %d%% of the time, slow ones %d%% '
                         '(%s, correlation %+.2f over %d).' % (label, med / 1000, round(strong(fast)),
                                                                round(strong(slow)), verdict, r, len(pts)))
        lines.append('Bots that see your showdowns learn these patterns and adjust your range by your timing.')
        return lines

    @staticmethod
    def _tilt(sessions):
        after, normal, after_net = [0, 0], [0, 0], 0.0
        for s in sessions:
            since = None
            for hd in s['hands']:
                in_win = since is not None and since < 10
                b = after if in_win else normal
                b[0] += 1
                b[1] += int(hd['vpip'])
                if in_win:
                    after_net += hd['net']
                if since is not None:
                    since += 1
                if hd['net'] <= -30:
                    since = 0
        if after[0] < 8:
            return ['Not enough hands after big losses (30+ bb) yet to judge (%d).' % after[0]]
        va, vn = after[1] / after[0], normal[1] / max(1, normal[0])
        change = (va / vn - 1) * 100 if vn else 0
        mood = 'you loosen up — classic tilt' if change > 15 else ('you tighten up' if change < -15 else 'you stay steady')
        return ['In the 10 hands after losing 30+ bb you play %d%% of hands vs %d%% normally (%+d%%): %s.' % (
                    round(100 * va), round(100 * vn), round(change), mood),
                'Your result in those stretches: %+.1f bb per 100 hands.' % (100 * after_net / after[0])]

    @staticmethod
    def _by_time(hands):
        buckets = [(0, 30), (30, 60), (60, 120), (120, 10 ** 9)]
        lines = []
        for lo, hi in buckets:
            hs = [hd for hd in hands if lo * 60 <= hd['t0'] < hi * 60]
            if len(hs) >= 10:
                lines.append('%s into a session: %d hands, %+.1f bb/100, playing %d%% of hands.' % (
                    ('%d-%d min' % (lo, hi)) if hi < 10 ** 9 else '%d+ min' % lo, len(hs),
                    100 * sum(h['net'] for h in hs) / len(hs), round(100 * sum(h['vpip'] for h in hs) / len(hs))))
        return lines or ['Play longer sessions (10+ hands per half hour) to compare early vs late.']

    @staticmethod
    def _fatigue(sessions):
        early, late = [], []
        for s in sessions:
            for hd in s['hands']:
                for d in hd['decisions']:
                    if d[2]:
                        (early if hd['t0'] < 1800 else late).append(d[2] / 1000)
        if len(early) >= 20 and len(late) >= 20:
            return ['After 30 minutes your decisions take %.1fs (vs %.1fs early).' % (_median(late), _median(early))]
        return []

    @staticmethod
    def _breaks(sessions):
        count, total, before, after = 0, 0.0, [], []
        for s in sessions:
            hs = s['hands']
            for i in range(1, len(hs)):
                gap = hs[i]['t0'] - hs[i - 1]['t1']
                if gap >= BREAK_SECONDS:
                    count += 1
                    total += gap
                    before += hs[max(0, i - 20):i]
                    after += hs[i:i + 20]
        if not count:
            return ['No breaks of %d+ minutes between hands yet.' % (BREAK_SECONDS // 60)]
        lines = ['%d break%s, %s in total (average %s).' % (count, '' if count == 1 else 's', _dur(total),
                                                             _dur(total / count))]
        if len(before) >= 10 and len(after) >= 10:
            lines.append('20 hands before a break: %+.1f bb/100; 20 hands after: %+.1f bb/100.' % (
                100 * sum(h['net'] for h in before) / len(before), 100 * sum(h['net'] for h in after) / len(after)))
        return lines

    @staticmethod
    def _positions(hands):
        by = {}
        for hd in hands:
            by.setdefault(hd['pos'], []).append(hd)
        order = ['UTG', 'UTG+1', 'UTG+2', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        return ['%-4s %4d hands  %+7.1f bb/100  plays %d%%' % (
            p, len(by[p]), 100 * sum(h['net'] for h in by[p]) / len(by[p]),
            round(100 * sum(h['vpip'] for h in by[p]) / len(by[p]))) for p in order if p in by]


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sxy / (sx * sy) if sx > 0 and sy > 0 else 0.0


def _dur(seconds):
    m = int(seconds // 60)
    return '%dh %02dm' % (m // 60, m % 60) if m >= 60 else '%dm %02ds' % (m, int(seconds % 60))
