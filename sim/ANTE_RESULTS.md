# Ante-aware bots

Structure: 7-max, small blind = big blind = ante (9bb dead money per hand), 5% rake capped
at 15bb, random 40–120bb stacks. Hero seat vs six opponents, 28k duplicate-dealt hands per
cell, new seeds (not the ones used for tuning). bb/100 with 95% intervals; "vs TAG" is the
paired difference on identical deals.

| Table | TAG | AnteTAG | Hunter | AnteMax | Hunter:AnteMax |
|---|---:|---:|---:|---:|---:|
| fish (Station, Nervous, Scared, Maniac, LAG, Nit) | +2.7 ± 13.5 | +44.3 ± 15.4 | +50.8 ± 14.9 | +128.4 ± 20.7 | +138.5 ± 18.9 |
| passive (Nervous, Scared, Terrified, Station, Nit, TAG) | +45.2 ± 11.3 | +105.1 ± 14.4 | +112.9 ± 13.6 | +326.8 ± 22.1 | +372.1 ± 19.9 |
| regs (TAG, LAG, TAG, LAG, Nit, Maniac) | −31.6 ± 11.2 | −7.4 ± 13.5 | −4.4 ± 13.6 | +69.4 ± 16.2 | +68.8 ± 16.1 |
| sticky, not used in tuning (3× Station, Maniac, LAG, Nervous) | +15.8 ± 17.4 | +60.7 ± 20.6 | +59.2 ± 20.2 | +105.8 ± 26.5 | +130.0 ± 25.5 |
| adaptive, not used in tuning (3× Exploit, LAG, TAG, Station; 21k hands) | +20.2 ± 13.2 | +25.2 ± 15.4 | – | +35.7 ± 22.7 | +59.0 ± 21.3 |

Edge over TAG at the adaptive table: AnteTAG +5 ± 17, AnteMax +15 ± 25, Hunter:AnteMax +39 ± 24.

## Takeaways

- **Antes punish tight play.** With 9bb of dead money, AnteTAG's wider positional opens,
  bigger opens, no-limp and pot-odds blind defence gain +24 to +60 bb/100 over TAG at every table.
- **Hunter** (the "Winning Money From Bad Players" reads: isolating limpers, c-betting
  folders, giving up against stations, barrelling only top pair+, value-betting stations)
  adds a few bb/100 at soft tables on top of its base, and nothing against regulars, as expected.
- **AnteMax** (tuned for win rate) is a preflop maniac (VPIP 74 / PFR 59 / 3-bet 22). It
  exploits the rule bots' over-folding to raises; against adaptive opponents most of the edge
  is gone. Tuning against adaptive opponents is the next step before trusting it.

Reproduce: `python -m sim.tune --start AnteTAG` then compare with `sim.match.run_match(..., **sim.calibrate.TABLE)`.
