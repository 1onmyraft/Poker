'''
Play Texas Hold'em against the simulator's bots (Hunter, AnteMax, Maniac, AnteTAG, fish, ...).

    python poker_bots_gui.py

Uses only the standard library (tkinter) plus the cards in resources/. Rules,
bots and hand evaluation come from sim/. Every hand can be saved in the
1onmyraftpoker text format (history/), so you can run
`python -m sim.backtest history/<file>.txt` on your own play afterwards.

Keys: F fold, C check/call, R bet/raise, Enter next hand.
'''
import math
import os
import struct
import sys
import tkinter as tk
import zlib
from datetime import datetime
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sim.cards import evaluate                      # noqa: E402
from sim.engine import Action, FOLD, CHECK, CALL, BET, RAISE, PREFLOP  # noqa: E402
from sim.handhistory import HAND_NAMES             # noqa: E402
from sim.session import Session, STRUCTURES, BOT_CHOICES, DEFAULT_LINEUP  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, 'resources')
W, H = 1000, 560                 # table canvas
CX, CY = W // 2, 262             # table centre
FELT = '#0b3d2e'
SPEEDS = {'Slow': 1100, 'Normal': 650, 'Fast': 250, 'Instant': 0}
BOT_INFO = {
    'Hunter': 'ante-aware TAG that reads opponents (isolates limpers, c-bets folders, value-bets stations)',
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


def load_png(path, master, bg=(0, 0, 0)):
    """Load a PNG as a Tk image on any Tk version.

    Returns (image or None, how it was loaded). None means every method failed and
    the caller should draw the card/table itself."""
    mode = os.environ.get('POKER_GUI_PNG', '')      # testing: decoder / put / blankppm / vector
    if mode == 'vector':
        return None, 'vector (forced)'
    if not mode:
        try:
            return tk.PhotoImage(master=master, file=path), 'Tk PNG'         # Tk 8.6+
        except tk.TclError:
            pass
        try:
            from PIL import Image, ImageTk                                 # Pillow, if installed
            return ImageTk.PhotoImage(Image.open(path), master=master), 'Pillow'
        except Exception:
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
    return None, 'vector (Tk could not show the image)'


SUIT_SYMBOL = {'s': '\u2660', 'h': '\u2665', 'd': '\u2666', 'c': '\u2663'}


class HumanAgent:
    '''The engine calls act(); we hand control to the GUI until a button is pressed.'''

    def __init__(self, app):
        self.app = app
        self.name = 'You'

    def new_hand(self, hand_id):
        pass

    def end_hand(self, h):
        pass

    def receive_cards(self, cards):
        self.app.hero_cards = cards

    def act(self, st):
        return self.app.ask_human(st)


class PokerApp:

    def __init__(self, root):
        self.root = root
        root.title("Texas Hold'em vs Bots")
        root.configure(bg=FELT)
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.closing = False
        self.images = {}
        self.image_methods = {}
        self.session = None
        self.in_hand = False
        self.choice = tk.StringVar()
        self.pause_var = tk.IntVar()
        self.speed = tk.StringVar(value='Normal')
        self.auto_deal = tk.BooleanVar(value=False)
        self.build_ui()
        self.root.after(50, self.setup_dialog)

    # ------------------------------------------------------------------ images
    def img(self, name):
        '''Tk image for a card / 'back' / 'table', or None if it has to be drawn by hand.'''
        if name not in self.images:
            path = {'back': 'card_back.png', 'table': 'table.png'}.get(name, 'deck/%s.png' % name)
            # transparent pixels are blended onto what's behind: the room for the table,
            # the table's felt for cards
            bg = (0x0b, 0x3d, 0x2e) if name == 'table' else (0x1a, 0xbc, 0x9c)
            img, how = load_png(os.path.join(RES, path), self.root, bg)
            self.images[name] = img
            self.image_methods[how] = self.image_methods.get(how, 0) + 1
        return self.images[name]

    def draw_card(self, x, y, card):
        img = self.img(card)
        if img is not None:
            self.canvas.create_image(x, y, image=img)
            return
        c = self.canvas
        if card == 'back':
            c.create_rectangle(x - 29, y - 43, x + 29, y + 43, fill='#c62828', outline='white', width=2)
            c.create_rectangle(x - 22, y - 36, x + 22, y + 36, outline='#ffcdd2')
            return
        rank, suit = card[0], card[1]
        colour = '#c62828' if suit in 'hd' else '#111111'
        rank = '10' if rank == 'T' else rank
        c.create_rectangle(x - 29, y - 43, x + 29, y + 43, fill='white', outline='#333', width=2)
        c.create_text(x - 20, y - 30, text=rank, fill=colour, font=('Helvetica', 15, 'bold'))
        c.create_text(x, y + 6, text=SUIT_SYMBOL[suit], fill=colour, font=('Helvetica', 30))

    def draw_table(self):
        img = self.img('table')
        if img is not None:
            self.canvas.create_image(CX, CY, image=img)
            return
        c = self.canvas
        c.create_oval(CX - 400, CY - 206, CX + 400, CY + 206, fill='#17a589', outline='#0e6655', width=14)

    # ---------------------------------------------------------------------- UI
    def build_ui(self):
        top = tk.Frame(self.root, bg=FELT)
        top.pack(fill='x', padx=10, pady=(8, 0))
        self.info = tk.Label(top, text='', fg='white', bg=FELT, font=('Helvetica', 14, 'bold'))
        self.info.pack(side='left')
        tk.Button(top, text='New session', command=self.setup_dialog).pack(side='right', padx=4)
        tk.Checkbutton(top, text='Auto-deal', variable=self.auto_deal, bg=FELT, fg='white',
                       selectcolor=FELT, activebackground=FELT).pack(side='right', padx=4)
        ttk.Combobox(top, textvariable=self.speed, values=list(SPEEDS), width=8,
                     state='readonly').pack(side='right')
        tk.Label(top, text='Bot speed:', fg='white', bg=FELT).pack(side='right', padx=(10, 2))

        self.canvas = tk.Canvas(self.root, width=W, height=H, bg=FELT, highlightthickness=0)
        self.canvas.pack(padx=10)

        ctl = tk.Frame(self.root, bg=FELT)
        ctl.pack(fill='x', padx=10, pady=4)
        self.b_fold = tk.Button(ctl, text='Fold (F)', width=8, command=lambda: self.choose('fold'))
        self.b_call = tk.Button(ctl, text='Check (C)', width=13, command=lambda: self.choose('call'))
        self.b_raise = tk.Button(ctl, text='Raise (R)', width=21, command=lambda: self.choose('raise'))
        self.amount = tk.IntVar(value=0)
        self.scale = tk.Scale(ctl, from_=0, to=100, orient='horizontal', length=170, showvalue=False,
                              variable=self.amount, bg=FELT, fg='white', highlightthickness=0,
                              command=lambda _v: self.update_raise_label())
        self.entry = tk.Entry(ctl, width=7, textvariable=self.amount)
        self.presets = [tk.Button(ctl, text=t, width=3 if len(t) < 3 else 5, command=lambda f=f: self.preset(f))
                        for t, f in (('½', 0.5), ('⅔', 0.667), ('Pot', 1.0), ('All-in', None))]
        self.b_next = tk.Button(ctl, text='Next hand ⏎', width=11, command=self.next_hand)
        for w in (self.b_fold, self.b_call, self.b_raise, self.scale, self.entry, *self.presets):
            w.pack(side='left', padx=3)
        self.b_next.pack(side='right', padx=3)

        log_frame = tk.Frame(self.root, bg=FELT)
        log_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.log_box = tk.Text(log_frame, height=8, bg='#0f2a22', fg='#e8e8e8', font=('Courier', 11),
                               state='disabled', wrap='word')
        sb = tk.Scrollbar(log_frame, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        self.log_box.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self.root.bind('<Key-f>', lambda e: self.key('fold'))
        self.root.bind('<Key-c>', lambda e: self.key('call'))
        self.root.bind('<Key-r>', lambda e: self.key('raise'))
        self.root.bind('<Return>', lambda e: self.next_hand() if self.b_next['state'] == 'normal' else None)
        self.set_controls(False)
        self.b_next.configure(state='disabled')

    def log(self, text):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', text + '\n')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    # ------------------------------------------------------------ setup dialog
    def setup_dialog(self):
        if self.in_hand:
            messagebox.showinfo('Hand in progress', 'Finish the current hand first.')
            return
        d = tk.Toplevel(self.root)
        d.title('New session')
        d.transient(self.root)
        d.grab_set()
        tk.Label(d, text='Game', font=('Helvetica', 13, 'bold')).grid(row=0, column=0, sticky='w', padx=10, pady=(10, 2))
        struct = tk.StringVar(value='ante')
        for i, (k, v) in enumerate(STRUCTURES.items()):
            tk.Radiobutton(d, text=v['label'], variable=struct, value=k).grid(row=1 + i, column=0, columnspan=3, sticky='w', padx=20)
        tk.Label(d, text='Buy-in (big blinds):').grid(row=3, column=0, sticky='w', padx=10)
        buy = tk.IntVar(value=100)
        tk.Spinbox(d, from_=20, to=500, increment=10, textvariable=buy, width=6).grid(row=3, column=1, sticky='w')

        tk.Label(d, text='Opponents', font=('Helvetica', 13, 'bold')).grid(row=4, column=0, sticky='w', padx=10, pady=(10, 2))
        kinds = [tk.StringVar(value=k) for k in DEFAULT_LINEUP + ['(empty)'] * (8 - len(DEFAULT_LINEUP))]
        for i, v in enumerate(kinds):
            tk.Label(d, text='Seat %d:' % (i + 2)).grid(row=5 + i, column=0, sticky='e', padx=(20, 4))
            ttk.Combobox(d, textvariable=v, values=['(empty)'] + BOT_CHOICES, width=12,
                         state='readonly').grid(row=5 + i, column=1, sticky='w')
            info = tk.Label(d, text='', fg='#555', anchor='w', width=70)
            info.grid(row=5 + i, column=2, sticky='w')
            v.trace_add('write', lambda *_a, v=v, info=info: info.configure(text=BOT_INFO.get(v.get(), '')))
            info.configure(text=BOT_INFO.get(v.get(), ''))

        styles = tk.BooleanVar(value=True)
        save = tk.BooleanVar(value=True)
        tk.Checkbutton(d, text='Show bot styles in their names (untick to practise reading them from the HUD)',
                       variable=styles).grid(row=13, column=0, columnspan=3, sticky='w', padx=10, pady=(10, 0))
        tk.Checkbutton(d, text='Save my hands to history/ (1onmyraftpoker format, for sim.backtest)',
                       variable=save).grid(row=14, column=0, columnspan=3, sticky='w', padx=10)

        def start():
            lineup = [v.get() for v in kinds if v.get() != '(empty)']
            if not lineup:
                messagebox.showerror('No opponents', 'Pick at least one opponent.', parent=d)
                return
            path = None
            if save.get():
                path = os.path.join(HERE, 'history', datetime.now().strftime('session_%Y%m%d_%H%M%S.txt'))
            self.session = Session(lineup, structure=struct.get(), buy_in_bb=int(buy.get()),
                                   history_path=path, label_styles=styles.get())
            d.destroy()
            self.log_box.configure(state='normal')
            self.log_box.delete('1.0', 'end')
            self.log_box.configure(state='disabled')
            self.log('New session: %s, %d bb buy-in. Opponents: %s' % (
                STRUCTURES[struct.get()]['label'], int(buy.get()), ', '.join(s.name for s in self.session.seats[1:])))
            if path:
                self.log('Saving hands to %s' % os.path.relpath(path, HERE))
            self.preload_images()
            self.draw_idle()
            self.b_next.configure(state='normal')
            self.next_hand()

        tk.Button(d, text='Start', width=14, command=start).grid(row=15, column=0, columnspan=3, pady=12)
        d.bind('<Return>', lambda e: start())

    # ---------------------------------------------------------------- drawing
    def seat_xy(self, t, radius=1.0):
        n = len(self.session.seats)
        ang = math.radians(90 + 360 * t / n)
        return CX + radius * 420 * math.cos(ang), CY + radius * 222 * math.sin(ang)

    def draw(self, view):
        '''view: dict with per-table-seat stacks, bets, folded, cards, labels, board, pot, actor, ...'''
        c = self.canvas
        c.delete('all')
        self.draw_table()
        s = self.session
        bb = s.bb
        # board and pot
        board = view.get('board', [])
        for i, card in enumerate(board):
            self.draw_card(CX - 132 + 66 * i, CY - 18, card)
        if view.get('pot') is not None:
            c.create_text(CX, CY + 48, text='Pot %s' % self.fmt(view['pot']), fill='white',
                          font=('Helvetica', 15, 'bold'))
        if view.get('banner'):
            c.create_text(CX, CY + 76, text=view['banner'], fill='#ffd54f', font=('Helvetica', 13, 'bold'))
        pos = view.get('positions', {})
        for t, seat in enumerate(s.seats):
            x, y = self.seat_xy(t)
            folded = view['folded'][t]
            winner = view.get('winners', {}).get(t, 0) > 0
            outline = '#ffd54f' if view.get('actor') == t else ('#66ff99' if winner else '#222')
            fill = '#2b2b2b' if folded else ('#1e4d8c' if seat.is_human else '#3a3a3a')
            c.create_rectangle(x - 80, y - 30, x + 80, y + 30, fill=fill, outline=outline, width=3)
            c.create_text(x, y - 16, text=seat.name, fill='white', font=('Helvetica', 12, 'bold'))
            c.create_text(x, y + 1, text='%s  (%.0f bb)' % (self.fmt(view['stacks'][t]), view['stacks'][t] / bb),
                          fill='#dddddd', font=('Helvetica', 11))
            lab = view.get('labels', {}).get(t, '')
            c.create_text(x, y + 18, text=lab, fill='#ffd54f' if lab else '#888', font=('Helvetica', 11, 'italic'))
            if pos.get(t):
                tag = pos[t]
                col = '#ffffff' if tag == 'BTN' else '#9ecbff'
                c.create_oval(x + 62, y - 44, x + 92, y - 14, fill=col, outline='black')
                c.create_text(x + 77, y - 29, text='D' if tag == 'BTN' else tag, font=('Helvetica', 9, 'bold'))
            hud = s.hud(t) if not seat.is_human else ''
            if hud:
                c.create_text(x, y + 42, text=hud, fill='#c5e1a5', font=('Helvetica', 10))
            # cards
            cards = view['cards'].get(t)
            if cards and not folded:
                cx, cy = self.seat_xy(t, 0.70)
                for k, card in enumerate(cards):
                    self.draw_card(cx - 18 + 36 * k, cy, card)
            # chips in front
            bet = view['bets'][t]
            if bet:
                bx, by = self.seat_xy(t, 0.40)
                bx -= 30
                c.create_oval(bx - 9, by - 9, bx + 9, by + 9, fill='#e53935', outline='white', width=2)
                c.create_text(bx + 14, by, text=self.fmt(bet), anchor='w', fill='white', font=('Helvetica', 11, 'bold'))

    @staticmethod
    def fmt(chips):
        return '{:,}'.format(chips)

    def draw_idle(self):
        s = self.session
        n = len(s.seats)
        pos = s.positions()
        self.draw({'stacks': [x.stack for x in s.seats], 'bets': [0] * n, 'folded': [False] * n,
                   'cards': {}, 'positions': pos, 'pot': None, 'labels': {}})
        self.update_info()

    def update_info(self):
        s = self.session
        hu = s.human
        net = hu.won
        self.info.configure(text='Hand %d   |   You: %s chips, %+.1f bb this session (%d buy-in%s)' % (
            s.hand_no, '{:,}'.format(hu.stack), net / s.bb, hu.buyins, '' if hu.buyins == 1 else 's'))

    # ---------------------------------------------------- engine <-> GUI glue
    def start_view(self):
        s = self.session
        n = len(s.seats)
        self.order = [(s.button + j) % n for j in range(n)]
        self.pos = s.positions()
        self.labels = {}
        self.street = PREFLOP
        self.hero_cards = None

    def view_from(self, st, actor=None):
        n = len(self.session.seats)
        stacks, bets, folded = [0] * n, [0] * n, [False] * n
        cards = {}
        for j, t in enumerate(self.order):
            stacks[t] = st.stacks[j]
            bets[t] = st.street_bets[j]
            folded[t] = st.folded[j]
            cards[t] = self.hero_cards if t == 0 else ['back', 'back']
        if st.street != self.street:
            self.street = st.street
            self.labels = {}
            self.log('--- %s: %s' % (st.street.upper(), ' '.join(st.board)))
        pot = st.pot - sum(st.street_bets)
        return {'stacks': stacks, 'bets': bets, 'folded': folded, 'cards': cards, 'board': st.board,
                'pot': pot, 'positions': self.pos, 'labels': self.labels, 'actor': actor}

    def before_action(self, t, st):
        if self.closing:
            raise QuitGame
        self.draw(self.view_from(st, actor=t))
        self.update_info()

    def after_action(self, t, st, a):
        name = self.session.seats[t].name
        if a.kind == FOLD:
            txt, lab = 'folds', 'Fold'
        elif a.kind == CHECK:
            txt, lab = 'checks', 'Check'
        elif a.kind == CALL:
            txt, lab = 'calls %s' % self.fmt(st.to_call), 'Call %s' % self.fmt(st.to_call)
        elif a.kind == BET:
            txt, lab = 'bets %s' % self.fmt(a.amount), 'Bet %s' % self.fmt(a.amount)
        else:
            txt, lab = 'raises to %s' % self.fmt(a.amount), 'Raise to %s' % self.fmt(a.amount)
        if (a.kind in (BET, RAISE) and a.amount >= st.max_raise_to) or \
                (a.kind == CALL and st.to_call >= st.stack):
            lab += ' (all-in)'
        self.labels[t] = lab
        self.log('%-14s %s' % (name, txt))
        if t != 0:
            self.pause(SPEEDS[self.speed.get()])

    def pause(self, ms):
        if ms <= 0 or self.closing:
            return
        self.root.after(ms, lambda: self.pause_var.set(self.pause_var.get() + 1))
        self.root.wait_variable(self.pause_var)

    def ask_human(self, st):
        self.hero_cards = st.hole
        view = self.view_from(st, actor=0)
        self.draw(view)
        self.cur = st
        legal = st.legal()
        self.set_controls(True)
        self.b_fold.configure(state='normal' if FOLD in legal else 'disabled')
        self.b_call.configure(text=('Call %s (C)' % self.fmt(st.to_call)) if st.to_call else 'Check (C)')
        can_raise = BET in legal or RAISE in legal
        for w in (self.b_raise, self.scale, self.entry, *self.presets):
            w.configure(state='normal' if can_raise else 'disabled')
        if can_raise:
            self.scale.configure(from_=st.min_raise_to, to=st.max_raise_to)
            self.amount.set(min(st.max_raise_to, max(st.min_raise_to, self.preset_amount(0.667))))
            self.update_raise_label()
        self.choice.set('')
        self.root.wait_variable(self.choice)
        self.set_controls(False)
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

    def preset_amount(self, frac):
        st = self.cur if hasattr(self, 'cur') else None
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
        st = getattr(self, 'cur', None)
        if st is None:
            return
        try:
            amt = int(self.amount.get())
        except (tk.TclError, ValueError):
            return
        verb = 'Raise to' if st.current_bet else 'Bet'
        allin = ' (all-in)' if amt >= st.max_raise_to else ''
        self.b_raise.configure(text='%s %s%s (R)' % (verb, self.fmt(amt), allin))

    def set_controls(self, on):
        for w in (self.b_fold, self.b_call, self.b_raise, self.scale, self.entry, *self.presets):
            w.configure(state='normal' if on else 'disabled')

    def choose(self, what):
        self.choice.set(what)

    def key(self, what):
        widget = {'fold': self.b_fold, 'call': self.b_call, 'raise': self.b_raise}[what]
        if str(widget['state']) == 'normal' and not isinstance(self.root.focus_get(), tk.Entry):
            self.choose(what)

    # --------------------------------------------------------------- the hand
    def next_hand(self):
        if self.in_hand or self.session is None:
            return
        self.in_hand = True
        self.b_next.configure(state='disabled')
        self.start_view()
        s = self.session
        self.log('\n=== Hand %d   (button: %s)' % (s.hand_no + 1, s.seats[s.button].name))
        try:
            res = s.play_hand(HumanAgent(self), observer=self)
        except QuitGame:
            return
        finally:
            self.in_hand = False
        self.show_result(res)
        if self.closing:
            return
        self.b_next.configure(state='normal')
        if self.auto_deal.get():
            self.root.after(2500, self.next_hand)

    def show_result(self, res):
        s = self.session
        h = res.history
        n = len(s.seats)
        stacks = [x.stack for x in s.seats]
        cards, folded = {}, [True] * n
        for j, t in enumerate(res.order):
            if j in h.showdown:
                cards[t] = h.hole[j]
                folded[t] = False
            elif t == 0:
                cards[t] = h.hole[j]
                folded[t] = False
        alive = {res.order[j] for j in range(n)} - {res.order[a.seat] for a in h.actions if a.kind == FOLD}
        for t in alive:
            folded[t] = False
            cards.setdefault(t, ['back', 'back'])
        labels = {}
        for j in h.showdown:
            t = res.order[j]
            labels[t] = HAND_NAMES[evaluate(h.hole[j] + h.board)[0]]
        winners = {t: v for t, v in res.net.items() if v > 0}
        banner = ', '.join('%s wins %s' % (s.seats[t].name, self.fmt(v + h.invested[res.order.index(t)]))
                           for t, v in winners.items())
        self.draw({'stacks': stacks, 'bets': [0] * n, 'folded': folded, 'cards': cards, 'board': h.board,
                   'pot': sum(h.invested), 'positions': self.pos, 'labels': labels, 'winners': winners,
                   'banner': banner})
        if h.board and self.street != 'river' and len(h.board) == 5:
            self.log('--- board: %s' % ' '.join(h.board))
        for j in h.showdown:
            t = res.order[j]
            self.log('%-14s shows %s (%s)' % (s.seats[t].name, ' '.join(h.hole[j]), labels[t]))
        self.log(banner or 'Pot returned')
        me = res.net.get(0, 0)
        self.log('You: %+d chips (%+.1f bb) this hand' % (me, me / s.bb))
        self.update_info()

    def on_close(self):
        self.closing = True
        self.choice.set('quit')
        self.pause_var.set(self.pause_var.get() + 1)
        self.root.after(10, self.root.destroy)


    def preload_images(self):
        '''Load every image up front (so any slow fallback happens once) and report how.'''
        if self.image_methods:
            return
        for name in ['table', 'back'] + [r + s for r in '23456789TJQKA' for s in 'shdc']:
            self.img(name)
        how = ', '.join('%s x%d' % kv for kv in sorted(self.image_methods.items()))
        self.log('Images (Python %s, Tk %s): %s' % (sys.version.split()[0], tk.TkVersion, how))


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
        ok = img is not None and _looks_right(img, w, h, rgb) if how != 'Tk PNG' else img is not None
        print('  %-14s -> %-38s %s' % (name, how, 'OK' if ok else 'PROBLEM'))
    root.destroy()


def main():
    if '--diagnose' in sys.argv:
        diagnose()
        return
    root = tk.Tk()
    PokerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
