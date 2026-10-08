<img src="/resources/icon.png" height=90 width=877>

# Poker

This is a simple Texas Hold 'em game running on MacOS. All scripts are written in pure Python. The main GUI is written using the Python module `PySimpleGUI`, and hand evaluation is done by refering to a hand value table pre-calculated together with Monte Carlo simulation. See [here](https://allenfrostline.com/2019/04/09/texas-holdem-series-4/) for detailed explanation of hand evaluation. Together with the GUI version, I also include here a primitive commmandline version with `ColorPrint` support, which you may download and include from this [repo](https://github.com/allenfrostline/Python-Color-Print). The two versions are supposed to work identically.

### Play against the bots (`poker_bots_gui.py`)

```
python poker_bots_gui.py
```

A tkinter table (standard library only, uses the card images in `resources/`) where you play
against any mix of the simulator's bots: **Hunter**, **AnteMax**, **Maniac**, **AnteTAG**, fish
(**Station**, **Nervous**, **Scared**, **Terrified**) and regulars (Nit, LAG, TAG, Exploit).
Choose the ante game (10/10 + 10 ante, like the sample histories) or a classic 5/10 game, the
buy-in, and each seat's bot. A HUD under each bot shows VPIP/PFR/3-bet, aggression and hands
seen; untick "show bot styles" to practise reading them from the HUD alone. Busted players
rebuy automatically. Hands are saved to `history/` in the 1onmyraftpoker format, so
`python -m sim.backtest history/<file>.txt` scores your own play against the bots.

Keys: F fold, C check/call, R bet/raise, Enter next hand. Any Python 3.8+ with tkinter works,
including the one bundled with Xcode/macOS: its old Tk 8.5 can't read PNG, so the GUI then loads
the card images with Pillow if installed, or its own small PNG decoder (about a second at start-up).
A python.org Python (Tk 8.6) looks and behaves best on macOS; on Linux install `python3-tk`.
Every loaded image is checked against the PNG; if Tk can't show images at all, cards and the
table are drawn as shapes instead. `python poker_bots_gui.py --diagnose` prints what your
Python/Tk does with the images, `--selftest` opens a window that only draws the table and a
board, and `--draw-cards` always draws cards as shapes (a workaround for Tk builds that won't
display images).
The original `poker_gui.py` needs PySimpleGUI 3 and an old matplotlib, and is left unchanged.

### Bot simulator (`sim/`)

A headless, dependency-free no-limit hold'em simulator for tuning bots (no GUI, no `hv.json` needed):

- `sim/engine.py`: NLHE rules engine (blinds, min-raise, short all-ins, side pots, all-in EV) that records structured hand histories.
- `sim/stats.py`: HUD-style tendency stats (VPIP, PFR, 3-bet, steal, fold-to-steal, c-bet, fold-to-c-bet, fold-vs-bet, AFq, WTSD, W$SD), tracked as count/opportunity pairs with small-sample shrinkage.
- `sim/bots.py`: rule bots (TAG, LAG, Nit, Station, Maniac, plus three levels of low-skill "scared" bots: Nervous, Scared, Terrified) and `ExploitBot`, which models opponents from its own stats tracker using public information only.
- `sim/match.py`: duplicate-dealing match runner reporting bb/100 with 95% confidence intervals.
- `sim/experiments.py`: the standard experiment suite; see [`sim/RESULTS.md`](sim/RESULTS.md) for the latest numbers.
- `sim/handhistory.py`: reads and writes hand histories in the `1onmyraftpoker` text format (7-max, antes, straddles, rake, cash-outs, run-it-twice) and replays them through the engine, checking every action matches.
- `sim/generate.py`: writes simulated hands in that format; `sim/backtest.py`: asks each bot what it would do at every Hero decision in a history file and scores it (see [`sim/examples/`](sim/examples)).

```
python -m sim.experiments              # full suite, ~5 min on 4 cores
python -m sim.experiments --scale 0.1  # quick run
python -m sim.generate --hands 500 --hero TAG --out hands.txt
python -m sim.backtest hands.txt --out report.md
python -m unittest tests.test_sim
```

### Usage

You don't need any Python or module dependencies installed on your Mac in order to just play the game. The app itself is standalone with everything packed inside it already. There're just two steps:

1. Download the app from [here](https://drive.google.com/file/d/1vpxAMru_WIOT3-9VLIs6PxqR5couAUEj/view?usp=sharing).
2. Double click it.

<p align="center"><img src="/resources/screenshot.png" width=80%></img></p>

Or rather, if you'd like to pack it yourself:

1. Download this [repo](https://github.com/allenfrostline/Poker).
2. Pack it using `PyInstaller` in `--onefile` mode.
3. Double click the app you just generated.

### To-Do's

There're several things to work on in plan:

- Fix bugs (please, don't again).
- Write up AI agents of different strategies (in progress):
    - Expected hand value optimization (Greedy);
    - Game theory optimal (GTO);
    - Evolutionary algorithm (EA);
    - Deep Q-Learning (DQN).

- Build a server-based version so multiple people can play on different divices.
- Build an Android version (proposed by author of `PySimpleGUI`, [MikeTheWatchGuy](https://github.com/MikeTheWatchGuy)).
- Fix GUI problems:
    - Resolution of image is **extremely** low and it looks ugly on Retina screens.
    - Button styles and other design-related issues.

### Known Bugs

Here are some bugs I'm trying to fix:

- Side pot. It's tricky and I havn't found a way to implement it simple.
- Side pot. It's tricky and I havn't found a way to implement it simple.
- ~~Freeze at start. The app starts and then freezes for a sec. This is because Python is openning the hand value table. Perhaps I should try threading for this particular task (no need for the rest of the game). I'll also try to compress the table in a better way (like functionize it).~~ Working on the animated `Popup` element in `PySimpleGUI`.

### Acknowledgement

I appreciate suggestions and encourage from anyone throughout the development (which may still continue for a long time, considering the considerable time I spent just on writing this primitive game). Special thanks to my friends who ever tried to play the game and found bugs starting from the commmandline version. Also, credit for MikeTheWatchGuy who wrote the `PySimpleGUI` module and helped me fix several bugs. Also, credit to [Freepik](https://www.freepik.com) from [www.flaticon.com](www.flaticon.com), who made this fantastic icon. Finally, I wanna give credit to myself for the nights I stayed up after lectures. There is nothing more fulfilling than realizing an impulse right away.
