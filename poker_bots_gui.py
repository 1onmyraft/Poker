'''
Play Texas Hold'em against the simulator's bots (Hunter, AnteMax, Maniac, AnteTAG, fish, ...).

    python poker_bots_gui.py

Standard library only (tkinter) plus the images in resources/. Rules, bots and hand
evaluation come from sim/. Every hand can be saved in the 1onmyraftpoker text format
(history/), so `python -m sim.backtest history/<file>.txt` scores your own play.

Keys: F fold, C or Space check/call, R raise, 1-4 bet sizes, Up/Down adjust the
amount by a big blind, Enter or Space next hand, H show/hide the coach,
O take the all-in cash out (insurance) when it is offered.
Options: --draw-cards (draw cards as shapes), --selftest, --diagnose.
'''
import math
import os
import random
import struct
import sys
import tkinter as tk
import zlib
from datetime import datetime
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sim.cards import describe, best_five, hand_code, evaluate, PF_PERCENTILE   # noqa: E402
from sim.engine import Action, Table, FOLD, CHECK, CALL, BET, RAISE  # noqa: E402
from sim.session import Session, STRUCTURES, BOT_CHOICES, DEFAULT_LINEUP, CASH_OUT_FEE  # noqa: E402
from sim.bots import make_bot, PRESETS                              # noqa: E402
from sim.profile import Profile                                     # noqa: E402
from sim.ranges import RangeTracker, equity                         # noqa: E402
from sim.strength import _draws                                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, 'resources')
W, H = 1000, 560                 # table canvas
CX, CY = W // 2, 262             # table centre
PROFILE_PATH = os.path.join(HERE, 'history', 'profile.json')
ROOM = '#0b3d2e'
ROOM_RGB = (0x0b, 0x3d, 0x2e)
FELT = ROOM
TABLE_FELT_RGB = (0x1a, 0xbc, 0x9c)
BASE_PAUSE = 850                 # ms a bot's action stays on screen at Normal speed
MAX_THINK_MS = 4500              # longest a bot's thinking dots run at Normal speed
SPEEDS = {'Slow': 1.6, 'Normal': 1.0, 'Fast': 0.45, 'Instant': 0.0}
AVATARS = ['You', 'Wizard', 'Hunter', 'AnteMax', 'Maniac', 'AnteTAG', 'Station', 'Nervous', 'Scared',
           'Terrified', 'Nit', 'LAG', 'TAG', 'Exploit']
CARD_WORD = {'A': 'Ace', 'K': 'King', 'Q': 'Queen', 'J': 'Jack', 'T': 'Ten', '9': 'Nine', '8': 'Eight',
             '7': 'Seven', '6': 'Six', '5': 'Five', '4': 'Four', '3': 'Three', '2': 'Two'}
COACHES = ['AnteMax', 'Wizard', 'Hunter', 'AnteTAG', 'Off']
COACH_BG = '#2a1f4a'
BOT_INFO = {
    'Wizard': 'thinks in ranges: knows what you could hold (card removal), equity-based decisions, solved short-stack shoves',
    'Hunter': 'Wizard + reads: isolates limpers, c-bets folders, value-bets stations',
    'AnteMax': 'hyper-aggressive preflop (VPIP ~74 / PFR ~59), gives up postflop',
    'Maniac': 'raises and bluffs constantly',
    'AnteTAG': 'solid ante-aware tight-aggressive baseline',
    'Station': 'fish: calls far too much, rarely raises',
    'Nervous': 'fish: plays too few hands, folds to big bets',
    'Scared': 'fish: almost never bluffs, folds to pressure',
    'Terrified': 'fish: plays scared money, folds to almost any bet',
    'Nit': 'very tight, only plays premiums',
    'LAG': 'loose-aggressive regular',
    'TAG': 'tight-aggressive regular (tuned for no-ante games)',
    'Exploit': 'TAG that adapts to your stats as it learns them',
}


def pretty(card):
    return card[0].replace('T', '10') + {'s': '\u2660', 'h': '\u2665', 'd': '\u2666', 'c': '\u2663'}[card[1]]


class QuitGame(Exception):
    pass


# ------------------------------------------------------------- image loading
# Tk only reads PNG from version 8.6. The Python that ships with Xcode/macOS still
# uses Tk 8.5, so fall back to Pillow if installed, then to a tiny PNG decoder.
FORCE_DECODER = os.environ.get('POKER_GUI_PNG') in ('decoder', 'put')   # for testing


def decode_png(path, bg=(0, 0, 0)):
    '''Decode an 8-bit, non-interlaced RGB/RGBA PNG; alpha is blended onto `bg`.
    Returns (width, height, rgb bytes).'''
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG: %s' % path)
    pos, idat = 8, []
    while pos < len(data):
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
        elif kind == b'IDAT':
            idat.append(chunk)
        elif kind == b'IEND':
            break
        pos += 12 + length
    if depth != 8 or ctype not in (2, 6) or interlace:
        raise ValueError('unsupported PNG format in %s' % path)
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(b''.join(idat))
    stride = w * bpp
    out = bytearray(w * h * 3)
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif ftype == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        o = y * w * 3
        if bpp == 3:
            out[o:o + w * 3] = line
        else:
            for x in range(w):
                r, g, bl, al = line[4 * x:4 * x + 4]
                out[o + 3 * x] = (r * al + bg[0] * (255 - al)) // 255
                out[o + 3 * x + 1] = (g * al + bg[1] * (255 - al)) // 255
                out[o + 3 * x + 2] = (bl * al + bg[2] * (255 - al)) // 255
        prev = line
    return w, h, bytes(out)


def _looks_right(img, w, h, rgb):
    """Check a loaded image really holds the picture: right size, and sampled pixels
    match the decoded PNG. Some Tk 8.5 builds accept image data but stay blank."""
    if not hasattr(img, 'get'):
        return True                  # e.g. Pillow's ImageTk.PhotoImage: can't sample, trust it
    try:
        if img.width() != w or img.height() != h:
            return False
        for fx, fy in ((0.5, 0.5), (0.3, 0.4), (0.7, 0.6), (0.5, 0.25), (0.45, 0.75)):
            x, y = int(fx * (w - 1)), int(fy * (h - 1))
            got = img.get(x, y)
            if isinstance(got, str):
                got = tuple(int(v) for v in got.split())
            k = (y * w + x) * 3
            if any(abs(int(a) - b) > 2 for a, b in zip(got, rgb[k:k + 3])):
                return False
        return True
    except (tk.TclError, ValueError, TypeError):
        return False


def load_png(path, master, bg=(0, 0, 0), cards_only_flag=True):
    """Load a PNG as a Tk image on any Tk version.

    Returns (image or None, how it was loaded). None means every method failed and
    the caller should draw the card/table itself."""
    mode = os.environ.get('POKER_GUI_PNG', '')      # testing: decoder / put / blankppm / vector
    if mode == 'vector' or ('--draw-cards' in sys.argv and cards_only_flag):
        return None, 'drawn as shapes (forced)'
    if not mode and tk.TkVersion >= 8.6:
        try:
            return tk.PhotoImage(master=master, file=path), 'Tk PNG'         # Tk 8.6+
        except tk.TclError:
            pass
    try:
        w, h, rgb = decode_png(path, bg)
    except (OSError, ValueError, zlib.error):
        return None, 'vector (could not decode %s)' % os.path.basename(path)
    if mode != 'put':
        try:
            if mode == 'blankppm':       # simulate a Tk that accepts the data but shows nothing
                img = tk.PhotoImage(master=master, width=w, height=h)
            else:
                img = tk.PhotoImage(master=master, data=b'P6\n%d %d\n255\n' % (w, h) + rgb, format='PPM')
            if _looks_right(img, w, h, rgb):
                return img, 'decoder + PPM'
        except tk.TclError:
            pass
    try:
        img = tk.PhotoImage(master=master, width=w, height=h)                # slowest
        rows = []
        for y in range(h):
            row = rgb[y * w * 3:(y + 1) * w * 3]
            rows.append('{' + ' '.join('#%02x%02x%02x' % tuple(row[3 * x:3 * x + 3]) for x in range(w)) + '}')
        img.put(' '.join(rows), to=(0, 0))
        if _looks_right(img, w, h, rgb):
            return img, 'decoder + put'
    except tk.TclError:
        pass
    if not mode:
        try:
            from PIL import Image, ImageTk                                 # Pillow, if installed
            return ImageTk.PhotoImage(Image.open(path), master=master), 'Pillow'
        except Exception:
            pass
    return None, 'drawn as shapes (Tk could not show the image)'


SUIT_SYMBOL = {'s': '\u2660', 'h': '\u2665', 'd': '\u2666', 'c': '\u2663'}


def short_hand(cards):
    '''Hand name that fits a seat panel: "Pair of Kings", "Straight to K", "Two Pair K & 5".'''
    v = evaluate(cards)
    r = {14: 'A', 13: 'K', 12: 'Q', 11: 'J', 10: '10'}
    rk = lambda x: r.get(x, str(x))
    cat = v[0]
    if cat == 1:
        return describe(cards)
    if cat == 2:
        return 'Two Pair %s & %s' % (rk(v[1]), rk(v[2]))
    return {0: '%s-high' % rk(v[1]), 3: 'Trips %ss' % rk(v[1]), 4: 'Straight to %s' % rk(v[1]),
            5: 'Flush %s-high' % rk(v[1]), 6: 'Full House', 7: 'Quads %ss' % rk(v[1]),
            8: 'Straight Flush'}[cat]


def ease(t):
    return 1 - (1 - t) ** 3


def money(n):
    return '{:,}'.format(int(round(n)))


class HumanAgent:
    '''The engine calls act(); we hand control to the GUI until a button or key is pressed.'''

    def __init__(self, app):
        self.app = app
        self.name = 'You'

    def new_hand(self, hand_id):
        pass

    def end_hand(self, h):
        pass

    def receive_cards(self, cards):
        self.app.on_deal(cards)

    def act(self, st):
        return self.app.ask_human(st)


class PokerApp:
    '''
    One display state (self.disp), drawn in full by draw(); animations are temporary
    sprites (tag "anim") moved on top of it, after which the new state is drawn.
    '''

    def __init__(self, root):
        self.root = root
        root.title("Texas Hold'em vs Bots")
        root.configure(bg=ROOM)
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.closing = False
        self.images = {}
        self.image_methods = {}
        self.session = None
        self.in_hand = False
        self.dialog_open = False
        self.hero_turn = False
        self.cur = None
        self.disp = None
        self.range_tracker = None
        self.profile = None
        self.choice = tk.StringVar()
        self.pause_var = tk.IntVar()
        self.speed = tk.StringVar(value='Normal')
        self.auto_deal = tk.BooleanVar(value=False)
        self.bankroll_shown = 0
        self.coach_kind = tk.StringVar(value='AnteMax')
        self.coach = None
        self.think_ms = None              # set by the session before each after_action
        self.cash_choice = tk.StringVar()
        self.cash_offer_open = False
        self.build_ui()
        self.bind_keys()
        self.bring_to_front()
        self.root.after(80, self.setup_dialog)

    # ================================================================ images
    def img(self, name):
        '''Tk image for a card, 'back', 'table' or 'avatar:<Kind>[_dim]'; None = draw by hand.'''
        if name not in self.images:
            if name.startswith('avatar:'):
                path = os.path.join('avatars', name[7:] + '.png')
                bg = TABLE_FELT_RGB
            else:
                path = {'back': 'card_back.png', 'table': 'table.png'}.get(name, 'deck/%s.png' % name)
                bg = ROOM_RGB if name == 'table' else TABLE_FELT_RGB
            full = os.path.join(RES, path)
            if os.path.exists(full):
                # --draw-cards only swaps the cards for shapes; avatars still try images
                img, how = load_png(full, self.root, bg, cards_only_flag=not name.startswith('avatar:'))
            else:
                img, how = None, 'missing'
            self.images[name] = img
            self.image_methods[how] = self.image_methods.get(how, 0) + 1
        return self.images[name]

    def preload_images(self):
        if self.image_methods:
            return
        names = ['table', 'back'] + [r + s for r in '23456789TJQKA' for s in 'shdc']
        names += ['avatar:%s%s' % (k, d) for k in AVATARS for d in ('', '_dim')]
        for name in names:
            self.img(name)
        how = ', '.join('%s x%d' % kv for kv in sorted(self.image_methods.items()))
        self.log('Images (Python %s, Tk %s): %s' % (sys.version.split()[0], tk.TkVersion, how), 'info')
        if tk.TkVersion < 8.6 and '--draw-cards' not in sys.argv:
            self.log('Old Tk: if cards are missing, restart with  --draw-cards  (or use a python.org Python)', 'info')

    # ============================================================== building
    def build_ui(self):
        top = tk.Frame(self.root, bg=ROOM)
        top.pack(fill='x', padx=12, pady=(8, 0))
        self.hand_lbl = tk.Label(top, text='', fg='#cfd8dc', bg=ROOM, font=('Helvetica', 13, 'bold'))
        self.hand_lbl.pack(side='left')
        # the money counter
        bank = tk.Frame(top, bg='#06261c', highlightbackground='#c9a227', highlightthickness=2)
        bank.pack(side='left', padx=(24, 0))
        tk.Label(bank, text='BANKROLL', fg='#c9a227', bg='#06261c',
                 font=('Helvetica', 9, 'bold')).pack(side='left', padx=(10, 6))
        self.bank_lbl = tk.Label(bank, text='0', fg='white', bg='#06261c', font=('Courier', 22, 'bold'), width=7,
                                 anchor='e')
        self.bank_lbl.pack(side='left')
        self.delta_lbl = tk.Label(bank, text='', fg='#9e9e9e', bg='#06261c', font=('Helvetica', 12, 'bold'),
                                  width=12, anchor='w')
        self.delta_lbl.pack(side='left', padx=(8, 10))

        tk.Button(top, text='New session', command=self.setup_dialog).pack(side='right', padx=4)
        tk.Button(top, text='My profile', command=self.show_profile).pack(side='right', padx=4)
        tk.Checkbutton(top, text='Auto-deal', variable=self.auto_deal, bg=ROOM, fg='white',
                       selectcolor=ROOM, activebackground=ROOM).pack(side='right', padx=4)
        ttk.Combobox(top, textvariable=self.speed, values=list(SPEEDS), width=8,
                     state='readonly').pack(side='right')
        tk.Label(top, text='Speed:', fg='white', bg=ROOM).pack(side='right', padx=(10, 2))
        coaches = [c for c in COACHES if c in PRESETS or c in ('Hunter', 'Off')]
        ttk.Combobox(top, textvariable=self.coach_kind, values=coaches, width=12,
                     state='readonly').pack(side='right')
        tk.Label(top, text='Coach [H]:', fg='#d1c4e9', bg=ROOM).pack(side='right', padx=(10, 2))
        self.coach_kind.trace_add('write', lambda *_a: self.refresh_coach())

        self.canvas = tk.Canvas(self.root, width=W, height=H, bg=ROOM, highlightthickness=0)
        self.canvas.pack(padx=10, pady=(6, 0))
        self.canvas.bind('<Button-1>', lambda e: self.root.focus_set())

        # plain-English "what's happening" bar. Fixed height: if it grew with its text the whole
        # window would re-layout, which flashes black on macOS's Tk 8.5.
        bar = tk.Frame(self.root, bg='#10372b', height=60)
        bar.pack(fill='x', padx=10, pady=(4, 0))
        bar.pack_propagate(False)
        self.status = tk.Label(bar, text='', bg='#10372b', fg='white', font=('Helvetica', 14, 'bold'),
                               anchor='w', padx=14, wraplength=W - 30, justify='left')
        self.status.pack(fill='both', expand=True)
        self.status_bar = bar
        # coach: what the chosen bot would do here, how sure it is, and timing reads.
        # Fixed height for the same reason as the status bar.
        cbar = tk.Frame(self.root, bg=COACH_BG, height=52)
        cbar.pack(fill='x', padx=10, pady=(3, 0))
        cbar.pack_propagate(False)
        self.coach_lbl = tk.Label(cbar, text='', bg=COACH_BG, fg='#e1d5ff', font=('Helvetica', 12),
                                  anchor='w', padx=14, wraplength=W - 30, justify='left')
        self.coach_lbl.pack(fill='both', expand=True)
        self.coach_shown = True
        self.hover_seat = None
        self.hover_job = None
        self.status_text = ''

        ctl = tk.Frame(self.root, bg=ROOM)
        ctl.pack(fill='x', padx=10, pady=6)
        self.b_fold = tk.Button(ctl, text='Fold  [F]', width=8, command=lambda: self.choose('fold'))
        self.b_call = tk.Button(ctl, text='Check  [C]', width=13, command=lambda: self.choose('call'))
        self.b_raise = tk.Button(ctl, text='Raise  [R]', width=19, command=lambda: self.choose('raise'))
        self.amount = tk.IntVar(value=0)
        self.scale = tk.Scale(ctl, from_=0, to=100, orient='horizontal', length=110, showvalue=False, takefocus=0,
                              variable=self.amount, bg=ROOM, fg='white', highlightthickness=0,
                              command=lambda _v: self.update_raise_label())
        digits = (self.root.register(lambda p: p == '' or p.isdigit()), '%P')
        self.entry = tk.Entry(ctl, width=7, textvariable=self.amount, validate='key', validatecommand=digits)
        self.entry.bind('<Return>', lambda e: (self.choose('raise'), 'break')[1])
        self.presets = [tk.Button(ctl, text='%s [%d]' % (t, i + 1), width=5, command=lambda f=f: self.preset(f))
                        for i, (t, f) in enumerate((('½', 0.5), ('⅔', 0.667), ('Pot', 1.0), ('All-in', None)))]
        self.b_next = tk.Button(ctl, text='Next hand [Enter]', width=14, command=self.next_hand)
        for w in (self.b_fold, self.b_call, self.b_raise, self.scale, self.entry, *self.presets):
            w.pack(side='left', padx=2)
        self.b_next.pack(side='right', padx=2)

        log_frame = tk.Frame(self.root, bg=ROOM)
        log_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.log_box = tk.Text(log_frame, height=4, bg='#0f2a22', fg='#cfd8dc', font=('Courier', 11),
                               state='disabled', wrap='word')
        for tag, colour in (('street', '#ffd54f'), ('hero', '#90caf9'), ('win', '#69f0ae'),
                            ('info', '#78909c'), ('bot', '#e0e0e0')):
            self.log_box.tag_configure(tag, foreground=colour)
        sb = tk.Scrollbar(log_frame, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        self.log_box.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.set_controls(False)
        self.b_next.configure(state='disabled')

    def bind_keys(self):
        # bind_all: works whichever widget has focus (buttons, slider, the amount box, ...)
        self.root.bind_all('<KeyPress>', self.on_key)

    def bring_to_front(self):
        '''A Tk window started from Terminal on macOS doesn't get keyboard focus by itself.'''
        try:
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(400, lambda: self.root.attributes('-topmost', False))
            self.root.focus_force()
        except tk.TclError:
            pass

    def on_key(self, e):
        if self.dialog_open or self.session is None:
            return
        k = (e.keysym or '').lower()
        if k == 'h' and not self.focus_in_entry():
            self.coach_shown = not self.coach_shown
            self.refresh_coach()
            return
        if self.cash_offer_open:
            if k == 'o':
                self.cash_choice.set('cash')
            elif k in ('r', 'return', 'kp_enter', 'space'):
                self.cash_choice.set('run')
            return
        if self.hero_turn:
            if k == 'f':
                self.press(self.b_fold, 'fold')
            elif k in ('c', 'k', 'space'):
                self.press(self.b_call, 'call')
            elif k in ('r', 'b'):
                self.press(self.b_raise, 'raise')
            elif k in ('1', '2', '3', '4') and str(self.presets[0]['state']) == 'normal' \
                    and not self.focus_in_entry():
                self.preset((0.5, 0.667, 1.0, None)[int(k) - 1])
            elif k in ('up', 'down') and str(self.b_raise['state']) == 'normal':
                step = self.session.bb * (1 if k == 'up' else -1)
                try:
                    cur = int(self.amount.get())
                except (tk.TclError, ValueError):
                    cur = self.cur.min_raise_to
                self.amount.set(max(self.cur.min_raise_to, min(self.cur.max_raise_to, cur + step)))
                self.update_raise_label()
        elif k in ('return', 'kp_enter', 'space', 'n') and str(self.b_next['state']) == 'normal':
            self.root.after(0, self.next_hand)

    def focus_in_entry(self):
        try:
            return self.root.focus_get() is self.entry
        except (KeyError, tk.TclError):      # ttk popdown focus bug on some Pythons
            return False

    def press(self, button, what):
        if str(button['state']) == 'normal':
            self.choose(what)

    def log(self, text, tag='bot'):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', text + '\n', tag)
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def say(self, text, colour='white', bg='#10372b'):
        self.status_text = text
        self.status_colours = (colour, bg)
        if self.hover_seat is None:
            self.status.configure(text=text, fg=colour, bg=bg)
            self.status_bar.configure(bg=bg)

    def hover_enter(self, t):
        # a seat is several canvas items; moving between them fires leave+enter, so debounce
        if self.hover_job:
            self.root.after_cancel(self.hover_job)
            self.hover_job = None
        if self.hover_seat != t:
            self.hover_seat = t
            self.explain_seat(t)

    def hover_leave(self):
        if self.hover_job:
            self.root.after_cancel(self.hover_job)
        self.hover_job = self.root.after(150, self.hover_restore)

    def hover_restore(self):
        self.hover_job = None
        self.hover_seat = None
        colour, bg = getattr(self, 'status_colours', ('white', '#10372b'))
        self.status.configure(text=self.status_text, fg=colour, bg=bg)
        self.status_bar.configure(bg=bg)

    # ========================================================= setup dialog
    def setup_dialog(self):
        if self.in_hand:
            messagebox.showinfo('Hand in progress', 'Finish the current hand first.')
            return
        self.dialog_open = True
        d = tk.Toplevel(self.root)
        d.title('New session')
        d.transient(self.root)
        d.protocol('WM_DELETE_WINDOW', lambda: (setattr(self, 'dialog_open', False), d.destroy()))
        tk.Label(d, text='Game', font=('Helvetica', 13, 'bold')).grid(row=0, column=0, sticky='w', padx=10, pady=(10, 2))
        struct = tk.StringVar(value='ante')
        for i, (k, v) in enumerate(STRUCTURES.items()):
            tk.Radiobutton(d, text=v['label'], variable=struct, value=k).grid(row=1 + i, column=0, columnspan=4, sticky='w', padx=20)
        tk.Label(d, text='Buy-in (big blinds):').grid(row=3, column=0, sticky='w', padx=10)
        buy = tk.IntVar(value=100)
        tk.Spinbox(d, from_=20, to=500, increment=10, textvariable=buy, width=6).grid(row=3, column=1, sticky='w')

        tk.Label(d, text='Opponents', font=('Helvetica', 13, 'bold')).grid(row=4, column=0, sticky='w', padx=10, pady=(10, 2))
        kinds = [tk.StringVar(value=k) for k in DEFAULT_LINEUP + ['(empty)'] * (8 - len(DEFAULT_LINEUP))]
        for i, v in enumerate(kinds):
            tk.Label(d, text='Seat %d:' % (i + 2)).grid(row=5 + i, column=0, sticky='e', padx=(20, 4))
            pic = tk.Label(d)
            pic.grid(row=5 + i, column=1, padx=2)
            ttk.Combobox(d, textvariable=v, values=['(empty)'] + BOT_CHOICES, width=12,
                         state='readonly').grid(row=5 + i, column=2, sticky='w')
            info = tk.Label(d, text='', fg='#555', anchor='w', width=64)
            info.grid(row=5 + i, column=3, sticky='w')

            def refresh(*_a, v=v, info=info, pic=pic):
                info.configure(text=BOT_INFO.get(v.get(), ''))
                img = self.small_avatar(v.get())
                pic.configure(image=img if img is not None else '')
                pic.image = img
            v.trace_add('write', refresh)
            refresh()

        styles = tk.BooleanVar(value=True)
        save = tk.BooleanVar(value=True)
        straddle = tk.BooleanVar(value=False)
        tk.Checkbutton(d, text='Straddle: UTG posts 2 big blinds every hand and acts last preflop (4+ players)',
                       variable=straddle).grid(row=13, column=0, columnspan=4, sticky='w', padx=10, pady=(10, 0))
        tk.Checkbutton(d, text='Show bot styles in their names (untick to practise reading them from the HUD)',
                       variable=styles).grid(row=14, column=0, columnspan=4, sticky='w', padx=10)
        tk.Checkbutton(d, text='Save my hands to history/ (1onmyraftpoker format, for sim.backtest)',
                       variable=save).grid(row=15, column=0, columnspan=4, sticky='w', padx=10)
        tk.Label(d, fg='#555', justify='left', text='Keys: F fold · C or Space check/call · R raise · 1-4 bet sizes '
                 '· ↑/↓ adjust by 1 bb · Enter or Space next hand · H coach · O cash out when offered').grid(row=16, column=0, columnspan=4, sticky='w', padx=10)

        def start():
            lineup = [v.get() for v in kinds if v.get() != '(empty)']
            if not lineup:
                messagebox.showerror('No opponents', 'Pick at least one opponent.', parent=d)
                return
            path = None
            if save.get():
                path = os.path.join(HERE, 'history', datetime.now().strftime('session_%Y%m%d_%H%M%S.txt'))
            if self.profile is not None:
                self.profile.end_session()
            self.profile = Profile(PROFILE_PATH)
            self.session = Session(lineup, structure=struct.get(), buy_in_bb=int(buy.get()),
                                   history_path=path, label_styles=styles.get(), profile=self.profile,
                                   straddle=straddle.get())
            self.coach = None
            known = self.session.tracker.get('You').hands
            if known:
                self.log('The bots remember you: %d hands from earlier sessions (see My profile).' % known, 'info')
            d.destroy()
            self.dialog_open = False
            self.log_box.configure(state='normal')
            self.log_box.delete('1.0', 'end')
            self.log_box.configure(state='disabled')
            self.log('New session: %s, %d bb buy-in.' % (STRUCTURES[struct.get()]['label'], int(buy.get())), 'info')
            if path:
                self.log('Saving hands to %s' % os.path.relpath(path, HERE), 'info')
            self.preload_images()
            self.bankroll_shown = self.session.human.stack
            self.update_bankroll(animate=False)
            self.reset_disp()
            self.draw()
            self.bring_to_front()
            self.b_next.configure(state='normal')
            self.next_hand()

        tk.Button(d, text='Start', width=14, command=start).grid(row=17, column=0, columnspan=4, pady=12)
        d.bind('<Return>', lambda e: start())

    def small_avatar(self, kind):
        if kind not in AVATARS:
            return None
        key = 'small:' + kind
        if key not in self.images:
            big = self.img('avatar:' + kind)
            self.images[key] = big.subsample(2) if big is not None and hasattr(big, 'subsample') else None
        return self.images[key]

    # ================================================================ geometry
    def seat_xy(self, t, radius=1.0):
        n = len(self.session.seats)
        ang = math.radians(90 + 360 * t / n)
        return CX + radius * 385 * math.cos(ang), CY + radius * 222 * math.sin(ang)

    def card_spot(self, t, k):
        x, y = self.seat_xy(t, 0.63)
        return x - 18 + 36 * k, y

    def bet_spot(self, t):
        x, y = self.seat_xy(t, 0.40)
        return x, y

    def board_spot(self, i):
        return CX - 132 + 66 * i, CY - 22

    POT = (CX, CY + 52)
    DECK = (CX, CY - 22)

    # ============================================================ disp state
    def reset_disp(self):
        s = self.session
        n = len(s.seats)
        self.disp = {
            'stacks': [x.stack for x in s.seats], 'bets': [0] * n, 'folded': [False] * n,
            'cards': {}, 'board': [], 'pot': 0, 'labels': {}, 'actor': None, 'winners': {},
            'positions': s.positions(), 'hands': {}, 'highlight': set(), 'street': None,
        }

    def sync(self, st):
        d = self.disp
        for j, t in enumerate(self.order):
            d['stacks'][t] = st.stacks[j]
            d['bets'][t] = st.street_bets[j]
            d['folded'][t] = st.folded[j]
        d['pot'] = st.pot - sum(st.street_bets)
        d['board'] = list(st.board)

    # ================================================================ drawing
    def draw(self):
        c = self.canvas
        c.delete('all')
        d = self.disp
        if d is None:
            return
        self.draw_table()
        # deck
        dx, dy = self.DECK
        if not d['board']:
            for k in range(3):
                self.draw_card(dx - 2 * k, dy - 2 * k, 'back')
        # board
        for i, card in enumerate(d['board']):
            x, y = self.board_spot(i)
            self.draw_card(x, y, card)
            if card in d['highlight']:
                c.create_rectangle(x - 32, y - 46, x + 32, y + 46, outline='#ffd54f', width=4)
        # pot
        if d['pot']:
            px, py = self.POT
            self.draw_chips(px - 50, py, d['pot'], big=True)
            c.create_text(px + 4, py, text='Pot  %s' % money(d['pot']), fill='white', anchor='w',
                          font=('Helvetica', 16, 'bold'), tags='pot_text')
        for t in range(len(self.session.seats)):
            self.draw_seat(t)
        c.update_idletasks()

    def draw_seat(self, t):
        c = self.canvas
        d = self.disp
        s = self.session
        seat = s.seats[t]
        x, y = self.seat_xy(t)
        folded = d['folded'][t]
        winner = d['winners'].get(t, 0) > 0
        acting = d['actor'] == t
        tag = 'seat%d' % t
        # cards (behind the panel)
        cards = d['cards'].get(t)
        if cards and not folded:
            for k, card in enumerate(cards):
                cx_, cy_ = self.card_spot(t, k)
                self.draw_card(cx_, cy_, card)
                if card in d['highlight']:
                    c.create_rectangle(cx_ - 31, cy_ - 45, cx_ + 31, cy_ + 45, outline='#ffd54f', width=3)
        # panel
        if acting:
            c.create_rectangle(x - 106, y - 41, x + 106, y + 41, outline='#ffd54f', width=4)
        outline = '#69f0ae' if winner else ('#ffd54f' if acting else '#11161a')
        fill = '#262b2f' if folded else ('#1e4d8c' if seat.is_human else '#37474f')
        c.create_rectangle(x - 100, y - 35, x + 100, y + 35, fill=fill, outline=outline, width=3, tags=tag)
        av = self.img('avatar:%s%s' % (self.avatar_kind(seat), '_dim' if folded else ''))
        if av is not None:
            c.create_image(x - 64, y, image=av, tags=tag)
        else:
            c.create_oval(x - 98, y - 34, x - 30, y + 34, fill='#546e7a', outline='white', width=2, tags=tag)
            c.create_text(x - 64, y, text=seat.name[:2], fill='white', font=('Helvetica', 16, 'bold'), tags=tag)
        name_col = '#78909c' if folded else 'white'
        c.create_text(x - 22, y - 20, text=seat.name, anchor='w', fill=name_col,
                      font=('Helvetica', 12, 'bold'), tags=tag)
        c.create_text(x - 22, y + 1, text=money(d['stacks'][t]), anchor='w', fill='#ffe082' if not folded else '#607d8b',
                      font=('Courier', 15, 'bold'), tags=(tag, 'stack%d' % t))
        lab = d['labels'].get(t)
        if lab:
            text, colour = lab
            w = 7 * len(text) + 14
            c.create_rectangle(x - 22, y + 13, x - 22 + w, y + 31, fill=colour, outline='', tags=tag)
            c.create_text(x - 15, y + 22, text=text, anchor='w', fill='white' if colour != '#ffd54f' else '#222',
                          font=('Helvetica', 10, 'bold'), tags=tag)
        pos = d['positions'].get(t)
        if pos:
            col = '#ffffff' if pos == 'BTN' else '#9ecbff'
            c.create_oval(x + 78, y - 47, x + 106, y - 19, fill=col, outline='black')
            c.create_text(x + 92, y - 33, text='D' if pos == 'BTN' else pos, font=('Helvetica', 9, 'bold'))
        hud = self.hud_words(t)
        if hud:
            c.create_text(x, y + 47, text=hud, fill='#a5d6a7', font=('Helvetica', 10), tags=tag)
        # chips in front
        bet = d['bets'][t]
        if bet:
            bx, by = self.bet_spot(t)
            self.draw_chips(bx - 14, by, bet)
            c.create_text(bx + 2, by, text=money(bet), anchor='w', fill='white', font=('Helvetica', 12, 'bold'))
        c.tag_bind(tag, '<Enter>', lambda e, t=t: self.hover_enter(t))
        c.tag_bind(tag, '<Leave>', lambda e: self.hover_leave())

    def avatar_kind(self, seat):
        return 'You' if seat.is_human else (seat.kind if seat.kind in AVATARS else 'TAG')

    def draw_chips(self, x, y, amount, big=False, tags=()):
        '''A little stack of chips; more and pricier-looking chips for bigger amounts.'''
        bb = self.session.bb
        n = 1 if amount < 5 * bb else (2 if amount < 20 * bb else (3 if amount < 60 * bb else 4))
        if big:
            n += 1
        colours = ['#e53935', '#1e88e5', '#43a047', '#212121', '#8e24aa']
        r = 11 if big else 9
        ids = []
        for k in range(n):
            col = colours[min(k, len(colours) - 1)]
            ids.append(self.canvas.create_oval(x - r, y - r - 4 * k, x + r, y + r - 4 * k, fill=col,
                                               outline='white', width=2, tags=tags))
        return ids

    def draw_card(self, x, y, card, tags=()):
        img = self.img(card)
        if img is not None:
            return [self.canvas.create_image(x, y, image=img, tags=tags)]
        c = self.canvas
        if card == 'back':
            return [c.create_rectangle(x - 29, y - 43, x + 29, y + 43, fill='#c62828', outline='white', width=2, tags=tags),
                    c.create_rectangle(x - 22, y - 36, x + 22, y + 36, outline='#ffcdd2', tags=tags)]
        rank, suit = card[0], card[1]
        colour = '#c62828' if suit in 'hd' else '#111111'
        rank = '10' if rank == 'T' else rank
        return [c.create_rectangle(x - 29, y - 43, x + 29, y + 43, fill='white', outline='#333', width=2, tags=tags),
                c.create_text(x - 20, y - 30, text=rank, fill=colour, font=('Helvetica', 15, 'bold'), tags=tags),
                c.create_text(x, y + 6, text=SUIT_SYMBOL[suit], fill=colour, font=('Helvetica', 30), tags=tags)]

    def draw_table(self):
        img = self.img('table')
        if img is not None:
            self.canvas.create_image(CX, CY, image=img)
            return
        self.canvas.create_oval(CX - 400, CY - 206, CX + 400, CY + 206, fill='#17a589', outline='#0e6655', width=14)

    # ========================================================== explanations
    def hud_words(self, t):
        s = self.session
        if s.seats[t].is_human:
            return ''
        p = s.tracker.players.get(s.seats[t].name)
        if not p or p.hands < 1:
            return ''
        if p.hands < 8:
            return 'reading... (%d hand%s)' % (p.hands, '' if p.hands == 1 else 's')
        return 'plays %d%% · raises %d%%' % (round(100 * p.rate('vpip', shrink=False)),
                                             round(100 * p.rate('pfr', shrink=False)))

    def explain_seat(self, t):
        s = self.session
        seat = s.seats[t]
        if seat.is_human:
            text = 'You: %s chips. Session %+.1f bb.' % (money(seat.stack), seat.won / s.bb)
        else:
            p = s.tracker.players.get(seat.name)
            style = BOT_INFO.get(seat.kind, '')
            if p and p.hands:
                pct = lambda k: '%d%%' % round(100 * p.rate(k, shrink=False)) if p.stats[k].opp else '-'
                text = ('%s (%d hands): plays %s, raises %s, 3-bets %s, folds to c-bets %s, aggression %.1f'
                        % (seat.name, p.hands, pct('vpip'), pct('pfr'), pct('three_bet'), pct('fold_cbet'), p.af()))
            else:
                text = '%s: no hands seen yet' % seat.name
            if style and not seat.name.startswith('Bot '):
                text += '\n' + style
        self.status.configure(text=text, fg='#ffe082', bg='#263238')
        self.status_bar.configure(bg='#263238')

    def hand_help(self, st):
        '''Plain-English description of the hero's spot.'''
        hole = st.hole
        if not st.board:
            code = hand_code(hole)
            top = 100 * PF_PERCENTILE[code]
            what = '%s %s (%s): top %d%% of starting hands' % (CARD_WORD[hole[0][0]], CARD_WORD[hole[1][0]],
                                                              'suited' if code.endswith('s') else
                                                              ('pair' if len(code) == 2 else 'offsuit'), max(1, round(top)))
        else:
            what = 'You have %s' % describe(hole + st.board)
            if len(st.board) < 5:
                fd, oe, gs = _draws(hole, st.board)
                extra = [n for n, f in (('flush draw', fd), ('open-ended straight draw', oe), ('gutshot', gs)) if f]
                if extra:
                    what += ' + ' + ' + '.join(extra)
        eq = self.hero_equity(st)
        if eq is not None:
            what += ' — you win %d%% vs their likely hands' % round(100 * eq)
        if st.to_call:
            need = 100.0 * st.to_call / (st.pot + st.to_call)
            return ('Your turn: %s to call into a %s pot (calling needs %d%%). %s.' %
                    (money(st.to_call), money(st.pot), round(need), what))
        return 'Your turn: nobody has bet — check or bet. Pot %s. %s.' % (money(st.pot), what)

    def hero_equity(self, st):
        '''Your chance to win against what the others could hold, using the same range model
        as the Wizard bot (their actions, their stats, and card removal for every card you
        can see). Preflop it only counts players who have put money in voluntarily.'''
        try:
            if self.range_tracker is None or self.range_tracker.stats is not self.session.tracker:
                self.range_tracker = RangeTracker(self.session.tracker)
            dead = list(st.hole) + list(st.board)
            if st.board:
                opp = [i for i in st.active_seats if i != st.seat]
            else:
                opp = sorted({a.seat for a in st.history if a.kind in (CALL, RAISE) and a.seat != st.seat}
                             & set(st.active_seats))
            if not opp:
                return None
            ranges = [self.range_tracker.range_for(st, i, dead) for i in opp]
            return equity(st.hole, st.board, ranges, samples=400, rng=random.Random(st.hand_id))
        except Exception:            # never let a hint break the game
            return None

    # ============================================================ animation
    def k(self):
        base = SPEEDS[self.speed.get()]
        if self.in_hand and self.disp and self.disp['folded'][0]:
            return base * 0.35          # you're out of the hand: fast-forward the rest
        return base

    def sleep(self, ms):
        if self.closing:
            raise QuitGame
        if ms <= 0:
            return
        self.root.after(int(ms), lambda: self.pause_var.set(self.pause_var.get() + 1))
        self.root.wait_variable(self.pause_var)
        if self.closing:
            raise QuitGame

    def frames(self, ms, step):
        '''Run step(progress 0..1, eased) over ~ms * speed milliseconds.'''
        dur = ms * self.k()
        if dur <= 0:
            step(1.0)
            return
        n = max(2, int(dur / 18))
        for i in range(1, n + 1):
            step(ease(i / n))
            self.canvas.update_idletasks()
            self.sleep(dur / n)

    def fly(self, items, start, end, ms=320):
        '''Move canvas items from start to end (both (x, y)), easing out.'''
        last = [0.0]

        def step(p):
            dx = (end[0] - start[0]) * (p - last[0])
            dy = (end[1] - start[1]) * (p - last[0])
            for it in items:
                self.canvas.move(it, dx, dy)
            last[0] = p
        self.frames(ms, step)

    def float_text(self, x, y, text, colour):
        item = self.canvas.create_text(x, y, text=text, fill=colour, font=('Helvetica', 20, 'bold'), tags='anim')
        self.frames(700, lambda p: self.canvas.coords(item, x, y - 40 * p))
        self.canvas.delete(item)

    def banner(self, text, ms=650):
        if self.k() <= 0:
            return
        c = self.canvas
        box = c.create_rectangle(CX - 130, CY - 96, CX + 130, CY - 58, fill='#000000', outline='#ffd54f',
                                 width=2, tags='anim')
        lab = c.create_text(CX, CY - 77, text=text, fill='#ffd54f', font=('Helvetica', 20, 'bold'), tags='anim')
        c.update_idletasks()
        self.sleep(ms * self.k())
        c.delete(box)
        c.delete(lab)

    def chips_fly(self, t_from, to_xy, amount, ms=300, from_xy=None):
        x0, y0 = from_xy or self.seat_xy(t_from, 0.85)
        ids = self.draw_chips(x0, y0, amount, tags='anim')
        self.fly(ids, (x0, y0), to_xy, ms)
        return ids

    def sweep_bets(self):
        '''Slide every bet into the pot.'''
        d = self.disp
        total = sum(d['bets'])
        if not total:
            return
        spots = [(self.bet_spot(t)[0] - 14, self.bet_spot(t)[1], amt) for t, amt in enumerate(d['bets']) if amt]
        start_pot = d['pot']
        d['bets'] = [0] * len(d['bets'])
        if self.k() > 0:
            self.draw()
            sprites = [(self.draw_chips(x, y, amt, tags='anim'), (x, y)) for x, y, amt in spots]
            tx, ty = self.POT[0] - 50, self.POT[1]
            last = [0.0]

            def step(p):
                for ids, (x0, y0) in sprites:
                    for i in ids:
                        self.canvas.move(i, (tx - x0) * (p - last[0]), (ty - y0) * (p - last[0]))
                last[0] = p
                self.canvas.itemconfigure('pot_text', text='Pot  %s' % money(start_pot + total * p))
            self.frames(380, step)
            self.canvas.delete('anim')
        d['pot'] = start_pot + total
        self.draw()

    def tween_stack(self, t, start, end, ms=350):
        self.frames(ms, lambda p: self.canvas.itemconfigure('stack%d' % t, text=money(start + (end - start) * p)))

    def update_bankroll(self, animate=True):
        s = self.session
        new = s.human.stack
        old = self.bankroll_shown
        net_bb = s.human.won / s.bb
        arrow = '▲' if net_bb > 0 else ('▼' if net_bb < 0 else '•')
        colour = '#69f0ae' if net_bb > 0 else ('#ff5252' if net_bb < 0 else '#9e9e9e')
        self.delta_lbl.configure(text='%s %+.1f bb' % (arrow, net_bb), fg=colour)
        if animate and new != old and self.k() > 0:
            flash = '#69f0ae' if new > old else '#ff5252'
            self.bank_lbl.configure(fg=flash)
            self.frames(900, lambda p: self.bank_lbl.configure(text=money(old + (new - old) * p)))
            self.sleep(200)
        self.bank_lbl.configure(text=money(new), fg='white')
        self.bankroll_shown = new
        self.hand_lbl.configure(text='Hand %d' % max(1, s.hand_no))

    # ======================================================= engine -> GUI
    def on_deal(self, hero_cards):
        '''Called by the engine right after dealing: animate antes, blinds and the deal.'''
        s = self.session
        d = self.disp
        n = len(s.seats)
        struct = s.struct
        self.say('Hand %d — %s has the button. Antes and blinds go in, cards are dealt.' % (
            s.hand_no, s.seats[s.button].name), '#ffe082')
        # antes
        if struct['ante']:
            sources = []
            for t in range(n):
                amt = min(struct['ante'], d['stacks'][t])
                d['stacks'][t] -= amt
                d['pot'] += amt
                sources.append(self.seat_xy(t, 0.85))
            self.draw()
            if self.k() > 0:
                sprites = [(self.draw_chips(x, y, 1, tags='anim'), (x, y)) for x, y in sources]
                tx, ty = self.POT[0] - 50, self.POT[1]
                last = [0.0]

                def step(p):
                    for ids, (x0, y0) in sprites:
                        for i in ids:
                            self.canvas.move(i, (tx - x0) * (p - last[0]), (ty - y0) * (p - last[0]))
                    last[0] = p
                self.frames(350, step)
                self.canvas.delete('anim')
                self.draw()
        # blinds
        sb_t = self.order[0] if n == 2 else self.order[1]
        bb_t = self.order[1] if n == 2 else self.order[2]
        for t, amt in ((sb_t, struct['small_blind']), (bb_t, struct['big_blind'])):
            amt = min(amt, d['stacks'][t])
            d['stacks'][t] -= amt
            d['bets'][t] += amt
            d['labels'][t] = ('SB %s' % money(amt) if t == sb_t else 'BB %s' % money(amt), '#455a64')
        self.draw()
        if s.straddler is not None:
            t = s.straddler
            amt = min(2 * s.bb, d['stacks'][t])
            self.sleep(250 * self.k())
            if self.k() > 0:
                self.chips_fly(t, (self.bet_spot(t)[0] - 14, self.bet_spot(t)[1]), amt, 260)
                self.canvas.delete('anim')
            d['stacks'][t] -= amt
            d['bets'][t] += amt
            d['labels'][t] = ('Straddle %s' % money(amt), '#6a1b9a')
            self.draw()
            self.log('%-14s straddles %s (acts last preflop)' % (s.seats[t].name, money(amt)),
                     'hero' if t == 0 else 'bot')
        # deal: two rounds, starting left of the button
        dealt = {}
        for rnd in range(2):
            for j in range(1, n + 1):
                t = self.order[j % n]
                if self.k() > 0:
                    ids = self.draw_card(*self.DECK, 'back', tags='anim')
                    self.fly(ids, self.DECK, self.card_spot(t, rnd), 140)
                dealt.setdefault(t, []).append('back')
                d['cards'][t] = list(dealt[t])
        self.canvas.delete('anim')
        d['cards'][0] = list(hero_cards)          # flip ours
        self.draw()
        self.log('You are dealt %s %s' % tuple(pretty(c) for c in hero_cards), 'hero')

    def before_action(self, t, st):
        if self.closing:
            raise QuitGame
        d = self.disp
        if st.street != d['street']:
            if d['street'] is not None:
                self.new_street(st)
            d['street'] = st.street
            d['labels'] = {k: v for k, v in d['labels'].items() if v[0] == 'Fold'}
        self.sync(st)
        d['actor'] = t
        self.draw()
        if t != 0:
            seat = self.session.seats[t]
            self.say('%s is thinking...' % seat.name, '#cfd8dc')

    def think(self, t, ms):
        '''Pulsing dots in the acting bot's panel.'''
        if ms <= 0:
            return
        x, y = self.seat_xy(t)
        item = self.canvas.create_text(x + 60, y - 20, text='', fill='#ffd54f', font=('Helvetica', 16, 'bold'),
                                       tags='anim')
        steps = max(1, int(ms / 150))
        for i in range(steps):
            self.canvas.itemconfigure(item, text='.' * (1 + i % 3))
            self.canvas.update_idletasks()
            self.sleep(ms / steps)
        self.canvas.delete(item)

    def new_street(self, st):
        d = self.disp
        self.sweep_bets()
        name = {'flop': 'FLOP', 'turn': 'TURN', 'river': 'RIVER'}[st.street]
        new = st.board[len(d['board']):]
        self.log('--- %s: %s' % (name, ' '.join(pretty(c) for c in st.board)), 'street')
        self.say('%s: %s   —   pot %s' % (name.title(), ' '.join(pretty(c) for c in st.board), money(d['pot'])),
                 '#ffd54f')
        self.banner(name)
        self.deal_board(new)

    def deal_board(self, cards):
        d = self.disp
        for card in cards:
            i = len(d['board'])
            if self.k() > 0:
                ids = self.draw_card(*self.DECK, 'back', tags='anim')
                self.fly(ids, (self.DECK[0] + 200, self.DECK[1]), self.board_spot(i), 260)
                self.canvas.delete('anim')
            d['board'].append(card)
            self.draw()
            self.sleep(120 * self.k())

    def after_action(self, t, st, a):
        d = self.disp
        s = self.session
        name = s.seats[t].name
        think = self.think_ms if t != 0 else None
        if think:
            # bots take longer when the decision is close for them: watch for it
            self.think(t, min(think, MAX_THINK_MS) * self.k())
        d['actor'] = None
        if a.kind == FOLD:
            txt, pill = 'folds', ('Fold', '#616161')
            if self.k() > 0 and d['cards'].get(t):
                ids = []
                for k_ in range(2):
                    ids += self.draw_card(*self.card_spot(t, k_), 'back', tags='anim')
                self.fly(ids, self.card_spot(t, 0), self.DECK, 260)
                self.canvas.delete('anim')
            d['folded'][t] = True
        elif a.kind == CHECK:
            txt, pill = 'checks', ('Check', '#1565c0')
        else:
            if a.kind == CALL:
                added = st.to_call
                txt, pill = 'calls %s' % money(added), ('Call %s' % money(added), '#2e7d32')
            else:
                added = a.amount - st.committed
                verb = 'bets' if a.kind == BET else 'raises to'
                txt = '%s %s' % (verb, money(a.amount))
                pill = ('%s %s' % ('Bet' if a.kind == BET else 'Raise to', money(a.amount)), '#c62828')
            if added >= st.stack:
                txt += ' (ALL-IN)'
                pill = ('ALL-IN %s' % money(st.committed + added), '#ff6f00')
            start = d['stacks'][t]
            if self.k() > 0:
                self.chips_fly(t, (self.bet_spot(t)[0] - 14, self.bet_spot(t)[1]), added, 280)
                self.tween_stack(t, start, start - added, 200)
                self.canvas.delete('anim')
            d['stacks'][t] = start - added
            d['bets'][t] += added
        d['labels'][t] = pill
        self.draw()
        line = '%s %s' % (name, txt)
        took = ''
        if think:
            took = '   [%.1fs%s]' % (think / 1000.0, self.speed_word(t, a, think))
        self.log('%-14s %s%s' % (name, txt, took), 'hero' if t == 0 else 'bot')
        if t != 0:
            self.say(line, '#ffffff')
            self.sleep(0.55 * BASE_PAUSE * self.k())

    def ask_human(self, st):
        self.cur = st
        self.hero_turn = True
        legal = st.legal()
        self.say(self.hand_help(st), '#ffffff', '#1e4d8c')
        advice = self.refresh_coach()
        self.set_controls(True)
        self.b_fold.configure(state='normal' if FOLD in legal else 'disabled')
        self.b_call.configure(text=('Call %s  [C]' % money(st.to_call)) if st.to_call else 'Check  [C]')
        can_raise = BET in legal or RAISE in legal
        for w in (self.b_raise, self.scale, self.entry, *self.presets):
            w.configure(state='normal' if can_raise else 'disabled')
        if can_raise:
            self.scale.configure(from_=st.min_raise_to, to=st.max_raise_to)
            self.amount.set(min(st.max_raise_to, max(st.min_raise_to, self.preset_amount(0.667))))
            if advice and advice[0].kind in (BET, RAISE):       # pre-fill the coach's size
                self.amount.set(min(st.max_raise_to, max(st.min_raise_to, advice[0].amount)))
            self.update_raise_label()
        else:
            self.b_raise.configure(text='Raise  [R]')
        self.choice.set('')
        self.root.wait_variable(self.choice)
        self.hero_turn = False
        self.set_controls(False)
        self.coach_say('')
        if self.closing:
            raise QuitGame
        c = self.choice.get()
        if c == 'fold':
            return Action(FOLD)
        if c == 'call':
            return Action(CALL if st.to_call else CHECK)
        try:
            amt = int(self.amount.get())
        except (tk.TclError, ValueError):
            amt = st.min_raise_to
        return Action(RAISE if st.current_bet else BET, max(st.min_raise_to, min(amt, st.max_raise_to)))

    # ================================================================ coach
    def coach_bot(self):
        kind = self.coach_kind.get()
        if kind == 'Off' or self.session is None:
            return None
        if self.coach is None or getattr(self, 'coach_for', None) != (kind, id(self.session)):
            bot = make_bot(kind, self.session.human.name, seed=1)
            # the coach sees what you see: the table's stats and timing reads
            if hasattr(bot, 'tracker') or getattr(getattr(bot, 'p', None), 'smart', False):
                bot.tracker = self.session.tracker
            self.coach, self.coach_for = bot, (kind, id(self.session))
        return self.coach

    def coach_advice(self, st):
        """(action, confidence, reason) from the coach bot for this spot, or None."""
        bot = self.coach_bot()
        if bot is None:
            return None
        try:
            bot.rng = random.Random(st.hand_id * 1000 + len(st.history))   # same advice if asked twice
            a = Table._sanitize(bot.act(st), st)
            return a, getattr(bot, 'last_confidence', None), getattr(bot, 'last_reason', '')
        except Exception:              # never let a hint break the game
            return None

    @staticmethod
    def action_words(a, st):
        if a.kind == FOLD:
            return 'FOLD'
        if a.kind == CHECK:
            return 'CHECK'
        if a.kind == CALL:
            return 'CALL %s' % money(st.to_call)
        allin = ' (all-in)' if a.amount >= st.max_raise_to else ''
        return '%s %s%s' % ('BET' if a.kind == BET else 'RAISE to', money(a.amount), allin)

    def speed_word(self, t, a, think):
        """' slow'/' fast' when this was unusual for the player, judged from their history."""
        z = self.session.tracker.timing(self.session.seats[t].name).z(a.kind, think)
        return ', slow for them' if z >= 1.0 else (', fast for them' if z <= -1.0 else '')

    def timing_reads(self, st):
        """Plain-English reads on how long opponents took this hand."""
        last = {}
        for e in st.history:
            if e.seat != st.seat and e.seat in st.active_seats and getattr(e, 'think_ms', None):
                last[e.seat] = e
        reads = []
        for seat, e in last.items():
            name = st.names[seat]
            tm = self.session.tracker.timing(name)
            z = tm.z(e.kind, e.think_ms)
            if abs(z) < 1.0:
                continue
            corr, n = tm.tell(e.kind)
            verb = {FOLD: 'fold', CHECK: 'check', CALL: 'call', BET: 'bet', RAISE: 'raise'}.get(e.kind, e.kind)
            if z > 0:
                text = '%s tanked %.1fs on the %s' % (name, e.think_ms / 1000.0, verb)
                meaning = ('slow has meant STRONG for them' if corr > 0.2 else 'slow has meant weak for them'
                           if corr < -0.2 else 'a close decision: usually a medium hand')
            else:
                text = '%s snapped %.1fs on the %s' % (name, e.think_ms / 1000.0, verb)
                meaning = ('fast has meant weak for them' if corr > 0.2 else 'fast has meant strong for them'
                           if corr < -0.2 else 'an easy decision: very strong or giving up')
            reads.append((abs(z), '%s (%s)' % (text, meaning)))
        return [r for _, r in sorted(reads, reverse=True)[:2]]

    def coach_say(self, text):
        self.coach_lbl.configure(text=text)

    def refresh_coach(self):
        """Update the coach panel for the current spot. Returns the advice (or None)."""
        if not self.coach_shown:
            self.coach_say('Coach hidden — press H to show it.')
            return None
        if not (self.hero_turn and self.cur is not None):
            if self.coach_kind.get() == 'Off':
                self.coach_say('Coach off. Pick one at the top right.')
            else:
                self.coach_say('Coach (%s) will suggest a play on your turn.' % self.coach_kind.get())
            return None
        st = self.cur
        advice = self.coach_advice(st)
        if advice is None:
            self.coach_say('Coach off.' if self.coach_kind.get() == 'Off' else '')
            return None
        a, conf, reason = advice
        if conf is None:
            sure = ''
        elif conf >= 0.75:
            sure = 'clear-cut (%d%% sure)' % round(100 * conf)
        elif conf >= 0.4:
            sure = 'leaning (%d%% sure)' % round(100 * conf)
        else:
            sure = 'close call (%d%% sure) — either is fine' % round(100 * conf)
        text = 'Coach %s: %s  ·  %s\nWhy: %s' % (self.coach_kind.get(), self.action_words(a, st), sure, reason)
        reads = self.timing_reads(st)
        if reads:
            text += '  ·  Reads: ' + '; '.join(reads)
        self.coach_say(text)
        return advice

    # ====================================================== insurance / cash out
    def offer_cash_out(self, offer):
        """Called by the session when you are all-in with cards to come. True = take it."""
        d = self.disp
        self.sweep_bets()
        for t, cards in offer['hands'].items():
            d['cards'][t] = list(cards)
        d['labels'] = {t: v for t, v in d['labels'].items() if t not in offer['hands']}
        self.draw()
        win = 100 * offer['win_chance']
        self.say('All-in! You win %d%% of runouts. Cash out now for %s (fee %s), or run it?' % (
            round(win), money(offer['payout']), money(offer['fee'])), '#ffe082', '#4a148c')
        if self.coach_shown and self.coach_kind.get() != 'Off':
            self.coach_say('Coach %s: RUN IT. The cash-out price is your fair share (%s) minus a %d%% fee, so '
                           'taking it costs %s on average. Only cash out to cut the swing.' % (
                               self.coach_kind.get(), money(int(round(offer['fair']))),
                               round(100 * CASH_OUT_FEE), money(offer['fee'])))
        c = self.canvas
        x, y = CX, CY + 95
        box = c.create_rectangle(x - 230, y - 34, x + 230, y + 34, fill='#1a1033', outline='#ffd54f', width=2,
                                 tags='offer')
        c.create_text(x, y - 18, text='INSURANCE  ·  %d%% to win  ·  pot share worth %s' % (
            round(win), money(int(round(offer['fair'])))), fill='white', font=('Helvetica', 11, 'bold'),
            tags='offer')
        b1 = tk.Button(c, text='Cash out %s  [O]' % money(offer['payout']),
                       command=lambda: self.cash_choice.set('cash'))
        b2 = tk.Button(c, text='Run it  [Enter]', command=lambda: self.cash_choice.set('run'))
        c.create_window(x - 85, y + 12, window=b1, tags='offer')
        c.create_window(x + 95, y + 12, window=b2, tags='offer')
        del box
        self.cash_offer_open = True
        self.cash_choice.set('')
        try:
            self.root.wait_variable(self.cash_choice)
        finally:
            self.cash_offer_open = False
            c.delete('offer')
            b1.destroy()
            b2.destroy()
        if self.closing:
            raise QuitGame
        took = self.cash_choice.get() == 'cash'
        self.coach_say('')
        if took:
            self.log('You cash out for %s (fee %s). The house now owns your share of the pot.' % (
                money(offer['payout']), money(offer['fee'])), 'hero')
        return took

    def preset_amount(self, frac):
        st = self.cur
        if st is None:
            return 0
        if frac is None:
            return st.max_raise_to
        if st.current_bet:
            return int(st.current_bet + frac * (st.pot + st.to_call))
        return int(frac * st.pot)

    def preset(self, frac):
        st = self.cur
        self.amount.set(max(st.min_raise_to, min(st.max_raise_to, self.preset_amount(frac))))
        self.update_raise_label()

    def update_raise_label(self):
        st = self.cur
        if st is None:
            return
        try:
            amt = int(self.amount.get())
        except (tk.TclError, ValueError):
            return
        verb = 'Raise to' if st.current_bet else 'Bet'
        allin = ' ALL-IN' if amt >= st.max_raise_to else ''
        self.b_raise.configure(text='%s %s%s  [R]' % (verb, money(amt), allin))

    def set_controls(self, on):
        for w in (self.b_fold, self.b_call, self.b_raise, self.scale, self.entry, *self.presets):
            w.configure(state='normal' if on else 'disabled')

    def choose(self, what):
        self.choice.set(what)

    # ================================================================ hands
    def next_hand(self):
        if self.in_hand or self.session is None or self.dialog_open:
            return
        self.in_hand = True
        self.b_next.configure(state='disabled')
        s = self.session
        for t in s.rebuy_busted():
            self.log('%s rebuys for %s' % (s.seats[t].name, money(s.buy_in)), 'info')
        n = len(s.seats)
        self.order = [(s.button + j) % n for j in range(n)]
        self.reset_disp()
        self.draw()
        self.log('\n=== Hand %d   (button: %s)' % (s.hand_no + 1, s.seats[s.button].name), 'street')
        self.hand_lbl.configure(text='Hand %d' % (s.hand_no + 1))
        try:
            res = s.play_hand(HumanAgent(self), observer=self)
            self.show_result(res)
            if self.profile is not None and s.hand_no % 3 == 0:
                self.profile.save()
        except (QuitGame, tk.TclError):
            return
        finally:
            self.in_hand = False
        if self.closing:
            return
        self.b_next.configure(state='normal')
        if self.auto_deal.get():
            self.root.after(int(1500 + 1500 * self.k()), self.next_hand)

    def show_result(self, res):
        s = self.session
        h = res.history
        d = self.disp
        d['actor'] = None
        board_before = len(d['board'])
        self.sweep_bets()
        cash = getattr(h, 'cashouts', {}).get(res.order.index(0))
        if cash:
            start = d['stacks'][0]
            self.tween_stack(0, start, start + cash[0], 350)
            d['stacks'][0] = start + cash[0]
            if self.k() > 0:
                x, y = self.seat_xy(0)
                self.float_text(x, y - 50, 'Cashed out %s' % money(cash[0]), '#ffd54f')
        # all-in before the river: run the board out with a little suspense
        if h.showdown and len(h.board) > board_before:
            self.say('All-in! Running out the board...', '#ff6f00')
            for j in h.showdown:
                d['cards'][res.order[j]] = list(h.hole[j])
            self.draw()
            self.sleep(500 * self.k())
            for i in range(board_before, len(h.board)):
                self.deal_board([h.board[i]])
                self.sleep(350 * self.k())
        # reveal showdown hands
        if h.showdown:
            for j in h.showdown:
                t = res.order[j]
                d['cards'][t] = list(h.hole[j])
                d['labels'][t] = (short_hand(h.hole[j] + h.board), '#4e342e')
                self.draw()
                self.log('%-14s shows %s %s  (%s)' % (s.seats[t].name, pretty(h.hole[j][0]), pretty(h.hole[j][1]),
                                                      describe(h.hole[j] + h.board)),
                         'hero' if t == 0 else 'bot')
                self.sleep(380 * self.k())
        # pay each pot
        total_won = {}
        for award in h.pot_awards:
            for j, amt in award:
                total_won[res.order[j]] = total_won.get(res.order[j], 0) + amt
        if cash:
            would = total_won.pop(0, 0)
            self.log('Without the cash out you would have %s.' % (
                'collected %s' % money(would) if would else 'lost the pot'), 'info')
        winners = {t: amt for t, amt in total_won.items() if amt}
        if winners:
            best_t = max(winners, key=winners.get)
            if h.showdown:
                j = res.order.index(best_t)
                five = best_five(h.hole[j] + h.board)
                d['highlight'] = set(five)
            for t, amt in sorted(winners.items()):
                d['winners'][t] = amt
                start = d['stacks'][t]
                self.draw()
                if self.k() > 0:
                    x, y = self.seat_xy(t, 0.85)
                    self.chips_fly(None, (x, y), amt, 450, from_xy=(self.POT[0] - 50, self.POT[1]))
                    self.canvas.delete('anim')
                d['pot'] = max(0, d['pot'] - amt)
                self.draw()
                self.tween_stack(t, start, start + amt, 450)
                d['stacks'][t] = start + amt
                if self.k() > 0:
                    x, y = self.seat_xy(t)
                    self.float_text(x, y - 50, '+%s' % money(amt), '#69f0ae')
            # final message
            parts = []
            for t, amt in winners.items():
                name = s.seats[t].name
                j = res.order.index(t)
                how = ('with %s' % describe(h.hole[j] + h.board)) if h.showdown else '— everyone else folded'
                parts.append('%s %s %s %s' % (name, 'win' if t == 0 else 'wins', money(amt), how))
            msg = '   |   '.join(parts)
            me_won = 0 in winners
            self.say(msg, '#69f0ae' if me_won else '#ffffff', '#1b5e20' if me_won else '#37474f')
            self.log(msg, 'win')
        d['pot'] = 0
        d['stacks'] = [x.stack for x in s.seats]
        self.draw()
        me = res.net.get(0, 0)
        if me:
            self.log('You: %+d chips (%+.1f bb) this hand' % (me, me / s.bb), 'hero')
        self.update_bankroll()

    def show_profile(self):
        '''Window with everything the game has learned about you.'''
        prof = self.profile or Profile(PROFILE_PATH)
        w = tk.Toplevel(self.root)
        w.title('My profile')
        txt = tk.Text(w, width=96, height=34, wrap='word', bg='#0f2a22', fg='#e0e0e0', font=('Helvetica', 12),
                      padx=12, pady=10)
        txt.tag_configure('h', foreground='#ffd54f', font=('Helvetica', 14, 'bold'))
        for head, lines in prof.report():
            txt.insert('end', head + '\n', 'h')
            for line in lines:
                txt.insert('end', '  ' + line + '\n')
            txt.insert('end', '\n')
        txt.insert('end', 'Saved on this computer only: %s\n' % os.path.relpath(PROFILE_PATH, HERE))
        txt.configure(state='disabled')
        tk.Button(w, text='Close', command=w.destroy).pack(side='bottom', pady=6)
        sb = tk.Scrollbar(w, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        txt.pack(side='left', fill='both', expand=True)

    def on_close(self):
        if self.profile is not None:
            try:
                self.profile.end_session()
            except OSError:
                pass
        self.closing = True
        self.choice.set('quit')
        self.pause_var.set(self.pause_var.get() + 1)
        self.root.after(10, self.root.destroy)


def diagnose():
    '''python poker_bots_gui.py --diagnose : report what this Python/Tk can do with the images.'''
    print('Python', sys.version.replace('\n', ' '))
    print('Tk', tk.TkVersion, '| Tcl', tk.TclVersion, '| windowing system:', end=' ')
    root = tk.Tk()
    root.withdraw()
    print(root.tk.call('tk', 'windowingsystem'))
    try:
        import PIL
        print('Pillow', PIL.__version__)
    except ImportError:
        print('Pillow not installed')
    for name in ('table.png', 'card_back.png', 'deck/As.png', 'deck/Td.png'):
        path = os.path.join(RES, name)
        img, how = load_png(path, root)
        w, h, rgb = decode_png(path)
        ok = img is not None and _looks_right(img, w, h, rgb)
        status = 'OK' if ok else ('OK (shapes)' if 'forced' in how else 'PROBLEM')
        print('  %-14s -> %-38s %s' % (name, how, status))
    root.destroy()


def selftest():
    '''python poker_bots_gui.py --selftest : draw the table and a board, nothing else.'''
    root = tk.Tk()
    root.title('Card display self-test')
    c = tk.Canvas(root, width=W, height=H, bg=FELT, highlightthickness=0)
    c.pack()
    tk.Label(root, text='You should see the table, five cards in the middle (images), and five '
                        'drawn cards along the bottom. Close the window when done.').pack(pady=6)
    keep = []
    table, how_t = load_png(os.path.join(RES, 'table.png'), root, (0x0b, 0x3d, 0x2e))
    if table is not None:
        c.create_image(CX, CY, image=table)
        keep.append(table)
    hows = []
    for i, card in enumerate(['As', 'Kh', 'Qd', 'Jc', 'Ts']):
        img, how = load_png(os.path.join(RES, 'deck', card + '.png'), root, (0x1a, 0xbc, 0x9c))
        hows.append(how)
        if img is not None:
            c.create_image(CX - 132 + 66 * i, CY - 18, image=img)
            keep.append(img)
        x, y = CX - 132 + 66 * i, H - 50
        colour = '#c62828' if card[1] in 'hd' else '#111111'
        c.create_rectangle(x - 29, y - 43, x + 29, y + 43, fill='white', outline='#333', width=2)
        c.create_text(x - 20, y - 30, text=card[0].replace('T', '10'), fill=colour, font=('Helvetica', 15, 'bold'))
        c.create_text(x, y + 6, text=SUIT_SYMBOL[card[1]], fill=colour, font=('Helvetica', 30))
    c.create_text(CX, 20, fill='white', font=('Helvetica', 12),
                  text='Tk %s - table: %s - cards: %s' % (tk.TkVersion, how_t, ', '.join(sorted(set(hows)))))
    root.mainloop()


def main():
    if '--diagnose' in sys.argv:
        diagnose()
        return
    if '--selftest' in sys.argv:
        selftest()
        return
    root = tk.Tk()
    PokerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
