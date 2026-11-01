# Elytra on tungsten's physics

The elytra pilot used to be a PI controller in AltoClef (`util/agent/ElytraPilot`, see
`docs/elytra-pilot.md`): rules for climbing, cruising and landing, tuned against an offline copy of the
glide physics. Physics belongs to tungsten and AltoClef should only decide where to go, so this work
moves the physics and the planning over:

```
AltoClef  util/agent/ElytraFlight   kit, take-off, landing, rings, pursuit, rockets from the inventory
              |  asks for a look and whether to fire, every 2 ticks
tungsten  elytra/ElytraSolver       candidate looks flown ahead, scored
              |  every candidate, tick by tick
tungsten  elytra/ElytraPhysics      vanilla glide + firework pull, one tick at a time
```

## The model: `ElytraPhysics`

`step(motion, yaw, pitch, rocket)` is `LivingEntity`'s gliding velocity followed by the pull a firework
gives its shooter (`FireworkRocketEntity#tick`); `predict()` flies a held look for n ticks and stops at
the first block the 0.6-wide gliding box touches.

Checked against the game, not just written down: `FlightLog` keeps the last two minutes of gliding per
tick (position, velocity, look, rocket pulling, collision; MCP `flightLog`), and
`tools/elytra/bench/physcheck.py` feeds each tick's velocity and look to the same formulas and
compares with the velocity the game had a tick later. Over 848 ticks of a 300-block flight:

| | median | 95th percentile | max |
|---|---|---|---|
| gliding (369 ticks) | 0.0000 | 0.0010 | 0.0025 |
| under a rocket, pull after the glide (476) | 0.0001 | 0.0001 | 0.21 * |
| under a rocket, pull before the glide | 0.0126 | 0.0318 | 0.21 |
| under a rocket, pull ignored | 0.168 | 0.397 | 0.84 |

blocks per tick of velocity. * the first and last tick of a rocket: the log sees the rocket entity a
tick late.

## The solver: `ElytraSolver`

Every couple of ticks, about 250 candidates: pitch -50..40 in steps of 6, yaw at 0, +-10, +-25, +-50
degrees off the goal, with and without firing a rocket now; then a finer pass around the winner
(pitch +-2, +-4, yaw +-5). Each is flown 40 ticks (2 s) ahead through `ElytraPhysics`. A candidate that
hits a block is out; the rest are scored:

- progress to the goal point (horizontal);
- minus the height error at the end;
- minus the shortfall of energy (height + v^2/2g) against the goal height at cruise speed. A surplus
  earns nothing: rewarding it made the first version climb 74 blocks over a flat world on rockets;
- minus a price per rocket (`elytraRocketCost`, blocks of progress; by default 12 in creative and
  40 in survival, where every rocket is paper and gunpowder);
- minus crowding: points of the path within `clearance` of a block;
- for rings, minus how close the path passes the ring's centre (segments, not ticks).

Holding one look for two seconds is only how far it looks ahead: the next plan comes two ticks later.
When every candidate hits something, the one that hits latest is flown (a rocket preferred).

`FlightViz` draws it in the world, in tungsten's new `FLIGHT` layer (`;settings renderFlight false`):
the target, the route, the flown trail coloured by the pilot's mode, the predicted glide (yellow,
orange while a rocket pulls, a red box where it would hit), the solver's runners-up in grey, a box per
rocket fired, the line and slot to a leader.

## Who flies when

`elytraSolver` (off by default) hands the solver the route (CRUISE, CLIMB, AVOID) and the pursuit beyond
14 blocks. Take-off and the approach stay with the PI pilot: it gets the controls back at its own cruise
height (20 over the terrain) when it starts the descent. Handed over low and fast over the spot, it
circled a block over the ground for half a minute, a rocket a second.

`flyRings` (MCP) always flies on the solver: ring centres in order; a ring counts when the flight
crosses its plane square to the way in, and `flyStatus.ringMiss` gives how far off centre each one was
(the larger of up/down and sideways, as a square frame sees it).

In pursuit every pursuer aims a second ahead of the leader, 6 blocks behind on their track and 5 to one
side: the side it is already on (it changes only 3 blocks past the track), so two pursuers keep apart
without crossing. Another glider within 10 blocks pushes the point sideways only, 6 blocks at most, and
the point is smoothed. On one shared point two pursuers flew wing in wing and landed 0.2 blocks apart.

## Numbers (test bench, 01.11.2026)

All 11 bench checks pass on both the pilot and the solver. Rockets and seconds:

| flight | PI pilot | solver, creative price (12) | solver, survival price (40) |
|---|---|---|---|
| 150 blocks | 1, 6.7 s | 2, 6.2 s | 2, 6.2 s |
| 500 blocks | 4, 18.5 s | 5, 17.3 s | 3, 17.6 s |
| 1000 blocks | 9, 40.9 s | 11, 32.4 s | 6, 34.8 s |
| low over a tree line | 3 | 3 | |
| six 7x7 rings | (solver only) | 5-6, 17 s, 0.3-1.7 off centre | |

Pursuit of a leader flying a five-point route (the leader spent 7-8 rockets): PI pilot 13-15 rockets,
14-16 blocks behind; solver 7-8 rockets, 23-33 blocks behind. The solver does not buy closeness with
rockets; how close it keeps is the follow point above.

Since the pursuers keep apart (the side, then the sideways push) the solver pursuer is worse: two runs
on 01.11 morning, leader 6-7 rockets, solver 9 and 9 rockets, 38 and 49 blocks behind (median); the PI
pilot 20 and 9 rockets, 17 and 10 behind. Not solved: closeness against rockets is the choice to make
(the solver prices a rocket at 12 blocks of progress and lets the leader go rather than pay).

Show course (11 rings, a glass tunnel, a slalom, a dive by the ground), solo: all 11 passed, at most
3.2 blocks off centre, 8 rockets; three bots two seconds apart: 33 of 33, 7-10 rockets each.

## The way through: cells, then a flight the physics can fly

With `elytraRouteSearch` on (and the solver), the way to the target is searched in two layers, on a
worker thread, while the glider circles or holds its look.

1. **Cells** (`AirRoute.cells`): the world in 4-block cells, a cell open when nothing in it has
   collision; A* over 26 neighbours, a climb dearer than a descent, a cell by a wall dearer, a cell
   the client has not got (beyond the view distance) dearer still. The chain is cut where it first
   enters unseen chunks: the flight goes as far as it has been seen, and the cut moves on as the
   chunks come in.
2. **A flight in the corridor** (`AirPlan`): the open cells within two of the chain (and around the
   start), their blocks read once into memory. A state is position, velocity, look and the ticks the
   rocket still pulls; a move holds one look for 8 ticks, with or without a fresh rocket, turned no
   faster than the bot turns, flown through `ElytraPhysics`. A move that touches a block (0.8 blocks of
   room kept around the body) or leaves the corridor is out. Cost: ticks, plus the rocket's price in
   ticks. Weighted A* with a lower bound of what is left: the corridor distance at top speed, and the
   rockets the energy (height + v^2/0.16) cannot do without -- a glide loses at least 0.099 of it a
   block, a rocket adds at most 45.

Why the second layer: the cells know where the gaps are, not whether a glider gets from a low one up to
a high one. A climb needs the speed taken in before it, so the rocket has to burn where the climb is
still seconds away, further than the solver's two seconds see. Flying the cells' corners as rings,
the bot stalled under the high gap.

**Flying the plan** (`ElytraFlight.flyAirPlan`): the plan's looks and rockets, tick by tick (a rocket used
a tick early, as it pulls from the tick after). A new plan is made from the state predicted 6 ticks
on, the old plan's looks held till then, whenever the glider is 1.5 blocks off the plan (a rocket pulls
20 to 31 ticks; the plan assumes 25) or the plan runs out, and every 2 s while the way is not all in
sight. Before every tick the plan's next 12 looks are flown from where the glider really is; if they
would hit, the solver steers that tick, through the plan a second on. No progress along the way for
6 s, or no plan three times: the corners are flown as rings, as before (`flySettings{routePlan:false}`
does that from the start, for a comparison).

Found on the way there (01.11):
- **Collisions were checked at the ends of each tick only.** At 1.7 blocks a tick a glide passed through
  a wall one block thick between two checks; a plan flew outside a glass hall and in through its
  side. `ElytraPhysics.blocked(from, to)` checks the box around both ends now; the solver's
  predictions use it too.
- **A target under a roof was a landing on the roof.** `landingY` took the top of the column. With the
  route search on, it lands on the floor under the height asked for. The maze "passes" before that were
  landings on the hall's roof; the bench now counts a pass only inside the hall.
- **Beyond the view distance the world reads as air.** At 8 chunks the client sees 128 blocks; the long
  maze is 240. Planned through the unseen, the way went along the outside of the hall, or over its
  roof, and had to turn back to the door when the far end came into sight.

On the bench, the compact maze (`mazeseries.py --compact`: the bench's three gaps, walls 25 apart, all
in sight from the take-off), ten flights each, a pass only when it lands inside the hall:

| | through | rockets | seconds |
|---|---|---|---|
| corners as rings (`routePlan:false`) | 5 of 10 | 3.0 | 10.5 |
| physics plan, creative price (12) | 9 of 10 (one of them after falling back to the corners) | 5.0 | 11.0 |
| physics plan, survival price (40) | 10 of 10 | 4.7 | 10.9 |

The plan buys the pass with a rocket or two more at the creative price: a rocket where the climb to
the high gap needs it. The failures left: a glider pushed off the plan by the rocket's random 20..31
ticks, near the edge of the low gap, where no new plan finds a way and it slides up the wall.

Prototype and measurements of the layer alone (`scratchpad`-style JS with the same physics, rocket
pulls drawn 20..31, the 6-tick replanning delay): four hall layouts (the bench's, high-low-high,
four walls, a zigzag), 20 flights each at both rocket prices: 155 of 160 through; the corners as
rings, 1 to 18 of 30.

## Not done yet

- **Exploring what is out of sight.** The long maze (beyond the view distance from the take-off) is
  flown by finding out: along the outside, back to the door, through the gaps. That works some of the
  time (one pass in three on the bench: 23 plans, 34 s, 12 rockets) and is the next thing to make
  dependable.
- **Landing on the solver** and figures (tricks) on it; the PI pilot still does both.
- Pursuers do not follow a leader through a tunnel: the goal point lies beyond the wall, so they go
  round and fall behind.

## Files

- `tungsten/.../elytra/ElytraPhysics.java`, `ElytraSolver.java`, `AirRoute.java` (cells, corridor),
  `AirPlan.java` (the flight in the corridor)
- `src/.../util/agent/ElytraFlight.java` (`steer`, `followSlot`, `startRings`), `FlightViz.java`,
  `FlightLog.java`, `FrameRecorder.java` (game-only video for the bench: `recordStart`/`recordStop`;
  ffmpeg named in `<game>/altoclef/recorder_ffmpeg.txt`)
- `tools/elytra/bench/` -- the bench (README there)
