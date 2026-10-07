# Backtest: generated_station_hero.txt

- Hands in file: **200**; replayed exactly through the engine: **200**
- Hero decisions examined: **401**
- Hero result: **₮26.75** (+267.5 bb, +134 bb/100) - includes cash-outs, after rake

## Hero tendencies over these hands

| VPIP | PFR | Limp | 3Bet | Steal | CBet | FCB | FvB | AFq | WTSD | W$SD | AF |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 40 | 9 | 31 | 3 | 36 | 56 | 32 | 21 | 10 | 63 | 60 | 0.31 |

(sample counts: VPIP 79/200, PFR 18/200, Limp 29/93, 3Bet 3/108, Steal 5/14, CBet 5/9, FCB 12/38, FvB 16/76, AFq 17/172, WTSD 42/67, W$SD 25/42)

## Bots vs Hero

Agreement = same action type as Hero at the same decision. The counterfactual compares Hero and the bot only on hands whose outcome for the bot is known exactly.

| Bot | Agree (all) | Preflop | Flop | Turn | River | Scored hands | Hero on scored | Bot on scored | Bot − Hero | Unscored |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TAG | 68% | 69% (229) | 63% (84) | 67% (52) | 69% (36) | 189 | +72.6 bb | -223.0 bb | **-295.6 ± 678 bb** | 11 |
| LAG | 70% | 74% (229) | 62% (84) | 63% (52) | 69% (36) | 167 | -180.4 bb | -133.4 bb | **+47.0 ± 548 bb** | 33 |
| Nit | 68% | 67% (229) | 63% (84) | 71% (52) | 78% (36) | 195 | +198.3 bb | -152.4 bb | **-350.7 ± 697 bb** | 5 |
| Nervous | 71% | 72% (229) | 64% (84) | 75% (52) | 72% (36) | 189 | +135.1 bb | -209.1 bb | **-344.2 ± 679 bb** | 11 |
| Scared | 71% | 72% (229) | 60% (84) | 73% (52) | 83% (36) | 191 | +92.0 bb | -248.1 bb | **-340.1 ± 696 bb** | 9 |
| Terrified | 67% | 69% (229) | 60% (84) | 65% (52) | 81% (36) | 191 | +123.6 bb | -159.9 bb | **-283.5 ± 683 bb** | 9 |
| Station | 98% | 100% (229) | 94% (84) | 98% (52) | 94% (36) | 192 | +342.9 bb | +342.9 bb | **+0.0 ± 0 bb** | 8 |
| Maniac | 58% | 59% (229) | 50% (84) | 54% (52) | 72% (36) | 111 | +24.3 bb | -0.1 bb | **-24.4 ± 226 bb** | 89 |

± is a 95% interval on the total difference. Unscored hands are ones where the bot would have played on differently from Hero, so its result can't be known from the log.

## Spots where most bots disagree with Hero

| Hand | Street | Hero cards | Board | Facing | Hero | Bots (TAG / Nit / LAG) | Hero net |
|---|---|---|---|---:|---|---|---:|
| #2007 | turn | 2d 2c | Jh 6s 3d 8c | 11.0 bb | call | fold / fold / fold | +110.2 bb |
| #1930 | flop | Kd Qh | 9h 7s Jc | 14.5 bb | call | fold / fold / fold | +88.9 bb |
| #1910 | preflop | Ah 9s | - | 1.0 bb | call | fold / fold / fold | -87.0 bb |
| #1897 | preflop | 2d 2s | - | 4.5 bb | call | fold / fold / fold | -83.0 bb |
| #1979 | flop | 5s Qs | Ac 4h 3h | 30.5 bb | call | fold / fold / fold | -79.0 bb |
| #1836 | flop | Jd Ah | 8c 6h 3c | 30.0 bb | call | fold / fold / fold | +78.8 bb |
| #1953 | preflop | Tc Js | - | 3.5 bb | call | fold / fold / fold | +69.6 bb |
| #1856 | flop | Kh As | 2c Qc 9d | 21.7 bb | call | fold / fold / fold | +63.5 bb |
| #1861 | flop | 4s As | 2h 2d Jd | 17.0 bb | call | fold / fold / raise 51.0 bb | +61.5 bb |
| #1950 | flop | Ah 4h | 2d 5s 9s | 19.5 bb | call | fold / fold / fold | -59.0 bb |
| #1929 | flop | 3c Ac | 6c Qs 9s | 9.2 bb | call | fold / fold / fold | -51.0 bb |
| #1855 | preflop | 5c 5d | - | 3.5 bb | call | fold / fold / fold | +50.7 bb |
| #1946 | flop | Ah Ts | 4c 2h Js | 18.0 bb | call | fold / fold / fold | +50.7 bb |
| #1824 | flop | Th 8h | Jc 7s Kc | 19.5 bb | call | fold / fold / fold | -40.0 bb |
| #1881 | preflop | Th Qs | - | 4.5 bb | call | fold / fold / fold | +30.5 bb |

## Why hands were unscored

| Bot | continues where Hero folded | different line |
|---|---:|---:|
| TAG | 0 | 11 |
| LAG | 0 | 33 |
| Nit | 0 | 5 |
| Nervous | 0 | 11 |
| Scared | 0 | 9 |
| Terrified | 0 | 9 |
| Station | 0 | 8 |
| Maniac | 21 | 68 |

## How much to trust this

This is 200 hands. In a 10bb-ante/blind game the swing per hand is large: a single stacked all-in is ~100 bb, so the intervals above are wide, and a bot "beating" Hero here mostly means it folded before a few big losing pots. Use it to find spots to study, then confirm with the simulator over 100k+ hands.
