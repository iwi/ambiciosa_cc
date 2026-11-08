# Validation report

- Software version: 1.0.0
- Python: 3.13.18
- Master seed: 20261108
- Games per configuration: 20,000
- Time: 113 s

**72 of 72 checks passed.** A check passes when |z| < 4, or for the distribution, when the KS distance is below 1.95/√n (0.1% level).

## Stop at 30

`threshold` {'threshold': 30}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 119.5190 | 119.1381 | z = -1.09 | pass |
| Median turns to target | 107.0000 | 107.0000 | z = +0.00 | pass |
| SD of turns to target | 49.5975 | 49.5493 | z = -0.11 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0063 | 0.0063 < 0.0138 | pass |
| Games stopped at the turn limit | 2.8404 | 3.0000 | z = +0.09 | pass |
| Mean turn score (far from target) | 8.4323 | 8.4725 | z = +1.54 | pass |
| Turns scoring nothing (far from target) | 0.6377 | 0.6377 | z = +0.08 | pass |
| Throws per turn (far from target) | 2.2216 | 2.2223 | z = +0.93 | pass |

## Stop at 50

`threshold` {'threshold': 50}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 161.7210 | 160.8853 | z = -1.43 | pass |
| Median turns to target | 140.0000 | 140.0000 | z = +0.00 | pass |
| SD of turns to target | 82.0630 | 81.0105 | z = -1.87 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0062 | 0.0062 < 0.0139 | pass |
| Games stopped at the turn limit | 203.4177 | 200.0000 | z = -0.24 | pass |
| Mean turn score (far from target) | 6.0459 | 6.0820 | z = +1.44 | pass |
| Turns scoring nothing (far from target) | 0.7843 | 0.7841 | z = -0.90 | pass |
| Throws per turn (far from target) | 2.7325 | 2.7337 | z = +1.30 | pass |

## Three throws

`max_throws` {'max_throws': 3}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 128.8153 | 128.6083 | z = -0.53 | pass |
| Median turns to target | 115.0000 | 115.0000 | z = +0.00 | pass |
| SD of turns to target | 54.7608 | 54.3925 | z = -0.78 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0038 | 0.0038 < 0.0138 | pass |
| Games stopped at the turn limit | 7.6112 | 8.0000 | z = +0.14 | pass |
| Mean turn score (far from target) | 7.7921 | 7.8163 | z = +0.90 | pass |
| Turns scoring nothing (far from target) | 0.6312 | 0.6308 | z = -0.95 | pass |
| Throws per turn (far from target) | 2.1989 | 2.1990 | z = +0.10 | pass |

## 50 points or 4 throws

`combined` {'threshold': 50, 'max_throws': 4, 'logic': 'or'}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 137.7697 | 137.4091 | z = -0.79 | pass |
| Median turns to target | 121.0000 | 121.0000 | z = +0.00 | pass |
| SD of turns to target | 64.8170 | 64.4399 | z = -0.72 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0067 | 0.0067 < 0.0138 | pass |
| Games stopped at the turn limit | 31.3910 | 40.0000 | z = +1.54 | pass |
| Mean turn score (far from target) | 7.2688 | 7.2693 | z = +0.02 | pass |
| Turns scoring nothing (far from target) | 0.7163 | 0.7160 | z = -1.13 | pass |
| Throws per turn (far from target) | 2.4956 | 2.4964 | z = +0.98 | pass |

## 40 points and 2 throws

`combined` {'threshold': 40, 'max_throws': 2, 'logic': 'and'}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 137.8004 | 137.9823 | z = +0.39 | pass |
| Median turns to target | 121.0000 | 121.0000 | z = +0.00 | pass |
| SD of turns to target | 65.2247 | 64.9285 | z = -0.56 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0057 | 0.0057 < 0.0138 | pass |
| Games stopped at the turn limit | 32.9936 | 30.0000 | z = -0.52 | pass |
| Mean turn score (far from target) | 7.2631 | 7.2504 | z = -0.47 | pass |
| Turns scoring nothing (far from target) | 0.7257 | 0.7254 | z = -0.84 | pass |
| Throws per turn (far from target) | 2.5281 | 2.5293 | z = +1.33 | pass |

## Coin flip 75%

`random` {'p_continue': 0.75}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 189.5923 | 190.1434 | z = +0.90 | pass |
| Median turns to target | 168.0000 | 168.0000 | z = +0.00 | pass |
| SD of turns to target | 85.3509 | 86.6870 | z = +2.53 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0061 | 0.0061 < 0.0139 | pass |
| Games stopped at the turn limit | 360.8445 | 360.0000 | z = -0.04 | pass |
| Mean turn score (far from target) | 5.0317 | 4.9593 | z = -1.80 | pass |
| Turns scoring nothing (far from target) | 0.6078 | 0.6073 | z = -0.98 | pass |
| Throws per turn (far from target) | 2.1176 | 2.1163 | z = -0.78 | pass |

## Safe ahead, going for the win

`game_state` {'leading_threshold': 30, 'trailing_threshold': 60, 'close_to_win_points': 100, 'close_threshold': None}; target 1000, turn limit 500; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 130.5487 | 130.3813 | z = -0.42 | pass |
| Median turns to target | 117.0000 | 117.0000 | z = +0.00 | pass |
| SD of turns to target | 56.2962 | 55.4706 | z = -1.80 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0076 | 0.0076 < 0.0138 | pass |
| Games stopped at the turn limit | 6.4015 | 4.0000 | z = -0.95 | pass |
| Mean turn score (far from target) | 8.4323 | 8.4507 | z = +0.72 | pass |
| Turns scoring nothing (far from target) | 0.6377 | 0.6381 | z = +1.24 | pass |
| Throws per turn (far from target) | 2.2216 | 2.2225 | z = +1.25 | pass |

## Loaded dice, changed scores

`threshold` {'threshold': 40}; target 1000, turn limit 500; face weights [1, 1, 1, 1, 1.5, 2], scores {'ace': 15, 'king': 5, 'three_tens': -150, 'three_nines': -200}; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 31.5875 | 31.4980 | z = -1.99 | pass |
| Median turns to target | 31.0000 | 31.0000 | z = +0.00 | pass |
| SD of turns to target | 6.3580 | 6.2742 | z = -1.96 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0081 | 0.0081 < 0.0138 | pass |
| Games stopped at the turn limit | 0.0000 | 0.0000 | – | pass |
| Mean turn score (far from target) | 32.3322 | 32.4601 | z = +2.58 | pass |
| Turns scoring nothing (far from target) | 0.3483 | 0.3468 | z = -2.34 | pass |
| Throws per turn (far from target) | 2.3702 | 2.3721 | z = +1.51 | pass |

## Short game, tight turn limit

`threshold` {'threshold': 60}; target 300, turn limit 25; 20,000 games.

| Figure | Exact | Simulated | Test | Result |
| --- | ---: | ---: | ---: | --- |
| Mean turns to target | 17.9992 | 18.0222 | z = +0.36 | pass |
| Median turns to target | 19.0000 | 19.0000 | z = +0.00 | pass |
| SD of turns to target | 4.8212 | 4.7854 | z = -0.97 | pass |
| Distribution of turns to target (KS distance) | 0.0000 | 0.0066 | 0.0066 < 0.0258 | pass |
| Games stopped at the turn limit | 14,363.4202 | 14,276.0000 | z = -1.37 | pass |
| Mean turn score (far from target) | 4.5534 | 4.6058 | z = +0.71 | pass |
| Turns scoring nothing (far from target) | 0.8301 | 0.8296 | z = -0.88 | pass |
| Throws per turn (far from target) | 2.8921 | 2.8914 | z = -0.22 | pass |
