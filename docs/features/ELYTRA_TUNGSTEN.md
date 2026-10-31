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
side; the side comes from the pursuer's name, and any other glider within 10 blocks pushes the point
away. On one shared point two pursuers flew wing in wing and landed 0.2 blocks apart.

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

Show course (11 rings, a glass tunnel, a slalom, a dive by the ground), solo: all 11 passed, at most
3.2 blocks off centre, 8 rockets; three bots two seconds apart: 33 of 33, 7-10 rockets each.

## Not done yet

- **A route search through the air** (the "BFS like the water one"): today the goal is a point 60 blocks
  ahead at cruise height, and obstacles are only seen two seconds ahead. A coarse 3D grid search for
  the way round (and under, and through) comes next.
- **Planning off the client thread, circling while it plans.** The solver runs on the client thread
  (a few milliseconds every other tick); a route search will not.
- **Landing on the solver** and figures (tricks) on it; the PI pilot still does both.
- Pursuers do not follow a leader through a tunnel: the goal point lies beyond the wall, so they go
  round and fall behind.

## Files

- `tungsten/.../elytra/ElytraPhysics.java`, `ElytraSolver.java`
- `src/.../util/agent/ElytraFlight.java` (`steer`, `followSlot`, `startRings`), `FlightViz.java`,
  `FlightLog.java`, `FrameRecorder.java` (game-only video for the bench: `recordStart`/`recordStop`)
- `tools/elytra/bench/` -- the bench (README there)
