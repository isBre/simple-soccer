# Elo ranking snapshot (2026-11-19, one-off)

> A one-off run made while adding Opus 5.5 High, before the Lab's own ranking (`lab/ladder.py`, Ranking page) existed. Its
> script was then dropped in favour of the ladder. Not on the ladder's scale: 3-minute matches here, 90 s there, and a draw-aware fit.

One ranking for every team: the 17 Rule Based League teams (Opus 5.5 High included), the 5 RL League teams and the 20 trained
nets in `models/` (played in RL Team 5's shirts). A full round robin on the 5v5 arena,
3-minute matches, every pair 4 times (2 fixed seeds per side), 3,444 matches. One Bradley-Terry fit with draws (Davidson, draw
factor 0.63) over all results, on the Elo scale (400 points = 10x the odds), average team = 1500; 95% intervals from 200 bootstrap
resamples of the matches.

Reading it: 31 of the 41 opponents of every team are nets, so the ranking mostly measures how a team does against nets. Opus 5.5
High is the top rule team (1331, about 250 above Silver Arrows, intervals not overlapping), mostly because it concedes far fewer
goals against the nets (1.62 per match; the other rule teams 3.1-4.0); against the rule teams alone it is level with Silver
Arrows head to head. jit8 is level with RL Team 5 within the intervals.

| # | Team | Kind | Elo | 95% interval | W | D | L | GF/match | GA/match |
|---|---|---|---|---|---|---|---|---|---|
| 1 | RL Team 5 | rl | 2255 | 2185-2362 | 136 | 16 | 12 | 4.38 | 0.70 |
| 2 | net jit8_best | net | 2226 | 2128-2370 | 133 | 18 | 13 | 4.07 | 0.62 |
| 3 | RL Team 4 | rl | 2141 | 2048-2248 | 128 | 15 | 21 | 3.99 | 1.08 |
| 4 | net x_anchor_wall_strong_best | net | 2123 | 2039-2243 | 125 | 18 | 21 | 3.85 | 0.90 |
| 5 | net x_anchor_wall_best | net | 2099 | 2012-2216 | 125 | 14 | 25 | 3.45 | 0.90 |
| 6 | net x_wide_persist_best | net | 2076 | 2006-2171 | 119 | 22 | 23 | 3.40 | 0.90 |
| 7 | net x_anchor_corner2_best | net | 2065 | 1974-2174 | 120 | 18 | 26 | 3.35 | 0.87 |
| 8 | net x_persist_mix_best | net | 2042 | 1965-2148 | 117 | 20 | 27 | 3.10 | 0.85 |
| 9 | net x_anchor_corner_strong_best | net | 2004 | 1931-2095 | 114 | 19 | 31 | 3.35 | 0.91 |
| 10 | net x_kickstart_persist_best | net | 1998 | 1916-2108 | 113 | 20 | 31 | 3.29 | 0.93 |
| 11 | net x_anchor_ctrl_best | net | 1993 | 1922-2081 | 113 | 19 | 32 | 3.29 | 1.00 |
| 12 | net x_persist_lr_best | net | 1993 | 1909-2079 | 113 | 19 | 32 | 3.24 | 0.89 |
| 13 | net x_kickstart_strong_best | net | 1966 | 1874-2053 | 108 | 24 | 32 | 3.07 | 0.93 |
| 14 | net x_wide_kickstart_best | net | 1960 | 1868-2068 | 112 | 15 | 37 | 3.12 | 1.07 |
| 15 | net team46_start | net | 1917 | 1843-2022 | 104 | 23 | 37 | 3.15 | 1.10 |
| 16 | RL Team 3 | rl | 1912 | 1835-2009 | 106 | 18 | 40 | 3.23 | 1.35 |
| 17 | net t46check_best | net | 1874 | 1794-1967 | 100 | 23 | 41 | 3.02 | 1.14 |
| 18 | net team46_w256 | net | 1852 | 1785-1940 | 100 | 19 | 45 | 3.07 | 1.16 |
| 19 | RL Team 2 | rl | 1756 | 1682-1845 | 88 | 26 | 50 | 2.84 | 1.50 |
| 20 | net x_kickstart_best | net | 1739 | 1663-1835 | 91 | 17 | 56 | 2.87 | 1.61 |
| 21 | net t48_best | net | 1611 | 1503-1708 | 80 | 18 | 66 | 2.46 | 2.13 |
| 22 | net t48_u100 | net | 1572 | 1462-1658 | 77 | 18 | 69 | 2.38 | 2.29 |
| 23 | RL Team | rl | 1446 | 1377-1534 | 71 | 11 | 82 | 2.74 | 2.33 |
| 24 | Opus 5.5 High | rule | 1331 | 1200-1462 | 47 | 42 | 75 | 1.07 | 1.62 |
| 25 | net t47_best | net | 1246 | 1126-1357 | 50 | 23 | 91 | 2.32 | 3.47 |
| 26 | net t46_best | net | 1195 | 1084-1297 | 46 | 23 | 95 | 1.87 | 3.37 |
| 27 | Silver Arrows | rule | 1079 | 994-1162 | 36 | 24 | 104 | 0.90 | 3.29 |
| 28 | Onyx Titans | rule | 1055 | 961-1126 | 35 | 22 | 107 | 0.94 | 3.47 |
| 29 | Granite Athletic | rule | 1043 | 945-1120 | 33 | 24 | 107 | 0.77 | 3.13 |
| 30 | Dune Hawks | rule | 990 | 888-1067 | 29 | 23 | 112 | 0.85 | 3.18 |
| 31 | Teal Tide | rule | 984 | 874-1085 | 31 | 18 | 115 | 0.82 | 3.40 |
| 32 | Rose Falcons | rule | 936 | 845-1018 | 25 | 22 | 117 | 0.81 | 3.45 |
| 33 | Maroon Bulls | rule | 912 | 819-979 | 19 | 30 | 115 | 0.62 | 3.48 |
| 34 | Borealis Wolves | rule | 893 | 785-969 | 20 | 25 | 119 | 0.65 | 3.45 |
| 35 | Ember City | rule | 887 | 781-982 | 24 | 16 | 124 | 0.70 | 3.66 |
| 36 | Mint Owls | rule | 875 | 780-942 | 23 | 16 | 125 | 0.66 | 3.30 |
| 37 | Aurora FC | rule | 875 | 767-966 | 20 | 22 | 122 | 0.54 | 3.19 |
| 38 | Harbor Sharks | rule | 869 | 774-946 | 19 | 23 | 122 | 0.87 | 3.79 |
| 39 | Lime Comets | rule | 862 | 741-956 | 23 | 14 | 127 | 0.78 | 3.54 |
| 40 | Sand Scorpions | rule | 856 | 724-935 | 21 | 17 | 126 | 0.61 | 3.76 |
| 41 | Cobalt Rangers | rule | 755 | 635-841 | 11 | 22 | 131 | 0.51 | 3.91 |
| 42 | Fern Valley | rule | 741 | 613-810 | 12 | 18 | 134 | 0.56 | 3.95 |
