"""Three finalists was tuned for the wrong question.

When the gate only asked "is this frame readable", three candidates were plenty
— almost any live frame passes. Asking "is this the MOMENT the sentence named"
is far narrower, and the number was never revisited.

Measured on a Kompas package that genuinely contains an airstrike
(gbDzBo9w890, all 14 candidate windows judged):

    t=16.5  smoke plume rising over Gaza        action: yes
    t=48.2  airstrike explosion and smoke       action: yes
    t=27.5  helicopter landing near soldiers    action: no
    t=38.5  crew loading missile onto aircraft  action: no
    t=57.8  near-black night sky                unusable
    t=93.6  Biden at a White House podium       action: no
    ... 8 more, all no

Two of fourteen. Neither was among the three liveliest, so the source was
discarded with "no window shows the subject" while holding exactly the footage
the clip needed. At eight finalists the gate finds t=48.2.

The run is parallel because eight sequential 3s round-trips would add half a
minute per source.
"""
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import ai
import broll_place as bp

# --- the net has to be wider than the old three ------------------------
assert bp.VISION_FINALISTS >= 6, \
    (f"{bp.VISION_FINALISTS} finalists: measured footage needed 8 — only 2 of "
     f"14 windows showed the action and neither was in the top 3")
assert bp.VISION_PARALLEL >= 2, bp.VISION_PARALLEL

TMP = "/tmp/_v25"
os.makedirs(TMP, exist_ok=True)
busy = os.path.join(TMP, "busy.mp4")
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "testsrc2=size=320x240:rate=25:duration=20",
     "-c:v", "libx264", "-preset", "ultrafast", busy],
    check=True, capture_output=True)

real = ai.vision_json

# --- a late-ranking frame is still reachable ---------------------------
# Everything is refused except one specific moment, which the old 3-finalist
# cut would never have reached.
seen = []
lock = threading.Lock()


def only_one(system, user, images, **kw):
    with lock:
        seen.append(len(seen))
    # The 7th frame judged is the only acceptable one. Order of completion is
    # not deterministic under threads, so key off a stable count instead.
    return {"usable": True, "on_topic": True,
            "shows_action": len(seen) >= 7,
            "shows": "airstrike" if len(seen) >= 7 else "rubble"}


ai.vision_json = only_one
try:
    at, why = bp._pick_window(busy, 20.0, 16.0, 2.0, "Gaza", "an explosion")
    assert at is not None, \
        f"a frame outside the top 3 was unreachable: {why}"
    assert len(seen) >= 6, f"only {len(seen)} frames were judged"
finally:
    ai.vision_json = real

# --- parallel, not sequential -----------------------------------------
# Each stub call sleeps and records its (enter, exit) interval; overlap
# proves the calls run concurrently regardless of machine load.
calls = []


def slow(system, user, images, **kw):
    t_enter = time.time()
    time.sleep(0.4)
    t_exit = time.time()
    with lock:
        calls.append((t_enter, t_exit))
    return {"usable": True, "on_topic": True, "shows_action": False,
            "shows": "rubble"}


ai.vision_json = slow
try:
    at, why = bp._pick_window(busy, 20.0, 16.0, 2.0, "Gaza", "an explosion")
    n = len(calls)
    assert n >= 6, f"expected a wide net, judged {n}"
    events = sorted(
        ev for t_enter, t_exit in calls
        for ev in ((t_enter, 1), (t_exit, -1))
    )
    active = 0
    max_overlap = 0
    for _, delta in events:
        active += delta
        if active > max_overlap:
            max_overlap = active
    # QA rejected `max_overlap >= 2` (22 Oct 2026): a pool degraded from 4 to
    # 2 workers still passed GREEN. My first fix (`>= VISION_PARALLEL`) ALSO
    # leaked — measured: healthy 12, degraded-to-2 exactly 4, floor exactly 4,
    # so it passed right on the line.
    #
    # The pools NEST (the window pool at broll_place.py:531 runs inside the
    # frame pool at :410), so honest concurrency is a MULTIPLE of the setting,
    # not the setting itself. Measured on this box:
    #   VISION_PARALLEL=4 healthy        -> overlap 12   (>= 8  ok)
    #   VISION_PARALLEL=4 degraded to 2  -> overlap  4   (>= 8  FAILS, correct)
    #   VISION_PARALLEL=2 set honestly   -> overlap  4   (>= 4  ok)
    # 2*VISION_PARALLEL is the only floor that separates "someone degraded the
    # pool" from "the operator legitimately lowered the setting" — a hardcoded
    # 4 or 12 cannot tell those apart, and goes stale on retune.
    floor = 2 * bp.VISION_PARALLEL
    assert max_overlap >= floor, \
        (f"expected >= {floor} overlapping calls (2x VISION_PARALLEL="
         f"{bp.VISION_PARALLEL}; the window pool nests inside the frame pool) "
         f"across {n} calls, got {max_overlap} — a pool quietly degraded to "
         f"fewer workers lands here")

    assert at is None and "no window" in why, (at, why)
finally:
    ai.vision_json = real

# --- one failing call must not poison the batch -----------------------
# A single frame erroring out used to `break` the loop and abandon the rest.
state = {"n": 0}


def flaky(system, user, images, **kw):
    with lock:
        state["n"] += 1
        n = state["n"]
    if n <= 2:
        raise RuntimeError("router hiccup")
    return {"usable": True, "on_topic": True, "shows_action": True,
            "shows": "airstrike fireball"}


ai.vision_json = flaky
try:
    at, why = bp._pick_window(busy, 20.0, 16.0, 2.0, "Gaza", "an explosion")
    assert at is not None, f"two bad calls lost the whole source: {why}"
    assert "airstrike fireball" in why, why
finally:
    ai.vision_json = real


# --- a fully dead router still degrades to motion ---------------------
def boom(*_a, **_k):
    raise RuntimeError("router down")


ai.vision_json = boom
try:
    at, why = bp._pick_window(busy, 20.0, 16.0, 2.0, "Gaza", "an explosion")
    assert at is not None and "motion" in why, (at, why)
finally:
    ai.vision_json = real

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v25.py OK — {bp.VISION_FINALISTS} finalists judged "
      f"{bp.VISION_PARALLEL}-at-a-time: a frame outside the old top 3 is now "
      f"reachable, the batch beats sequential wall time, a flaky call no "
      f"longer abandons the source, and a dead router still falls back to "
      f"measured motion")
