"""A shortlist has to actually be a shortlist.

v23 reported "1 sources checked" while _gather_inserts was written to try
three. Two independent caps were responsible:

1. vetted() defaults to limit=1, so the "shortlist" handed to the retry loop
   was always a single hit no matter how many candidates passed.
2. The 20k view floor was applied to verified broadcasters too. Searches for
   the Gaza strikes returned 7-8 relevant Kompas/CNN packages and exactly one
   cleared it — real Palestinian footage from verified channels was being
   discarded for having 7k views, which is a quiet news day, not a hoax.

Measured on this box, searching 'Palestina' + the action term:

    term      candidates  passed before  passed after
    dibantai       7            1             3
    dibom          8            1             3
    diserang       6            1             3

Every survivor is from a verified channel.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll
import job

BIG = {"id": "a", "title": "Serangan Israel di Gaza", "view_count": 800000,
       "channel_is_verified": True, "channel_follower_count": 9_000_000,
       "upload_date": "20250101", "duration": 120}


def hit(**over):
    out = dict(BIG)
    out.update(over)
    return out


# --- a verified channel clears a much lower floor ----------------------
ok, why = broll.credible(hit(view_count=7214))
assert ok, f"verified footage with 7214 views was rejected: {why}"

ok, why = broll.credible(hit(view_count=603))
assert ok, f"verified footage with 603 views was rejected: {why}"

# --- but the floor still exists ----------------------------------------
ok, why = broll.credible(hit(view_count=12))
assert not ok and "below" in why, (ok, why)

# --- an unverified channel is still held to the high floor -------------
# This is the whole point of the split: the view count was never about
# popularity, it was a proxy for accountability, and verification replaces it.
ok, why = broll.credible(hit(view_count=7214, channel_is_verified=False,
                             channel_follower_count=10))
assert not ok, "an unverified channel must not inherit the verified floor"
assert "followers" in why or "below" in why, why

ok, why = broll.credible(hit(view_count=50000, channel_is_verified=False,
                             channel_follower_count=10))
assert not ok and "followers" in why, (ok, why)

# A big unverified channel is accountable by reach, and then the low floor
# applies to it as well.
ok, why = broll.credible(hit(view_count=600, channel_is_verified=False,
                             channel_follower_count=2_000_000))
assert ok, f"a 2M-follower channel was rejected: {why}"

# --- the floors must be far enough apart to matter ---------------------
assert broll.MIN_VIEWS_VERIFIED < broll.MIN_VIEWS / 10, \
    (broll.MIN_VIEWS_VERIFIED, broll.MIN_VIEWS)

# --- vetted() returns as many as asked for -----------------------------
hits = [hit(id=c, view_count=v) for c, v in
        (("a", 900), ("b", 800), ("c", 700), ("d", 600))]
real_probe = broll.probe_meta
broll.probe_meta = lambda vid: {"id": vid}
try:
    got = broll.vetted(hits, ["serangan"], limit=3)
    assert len(got) == 3, f"asked for 3, got {len(got)}"
    # Best first: the retry loop depends on this order.
    assert [h["id"] for h in got] == ["a", "b", "c"], got
    assert len(broll.vetted(hits, ["serangan"])) == 1, \
        "the default must stay 1 for callers that want a single source"
finally:
    broll.probe_meta = real_probe

# --- and job.py asks for more than one ---------------------------------
assert job.BROLL_SOURCE_TRIES >= 2, job.BROLL_SOURCE_TRIES

src = open(os.path.join(os.path.dirname(os.path.dirname(
                             os.path.abspath(__file__))),
                        "job.py"), encoding="utf-8").read()
assert "limit=BROLL_SOURCE_TRIES" in src, \
    "job.py calls vetted() without raising the limit, so the retry loop " \
    "still only ever sees one source"

print(f"_v24.py OK — verified channels clear a {broll.MIN_VIEWS_VERIFIED}-view "
      f"floor instead of {broll.MIN_VIEWS} (7214 and 603 now pass, 12 still "
      f"fails, unverified unchanged); vetted(limit=3) returns 3 best-first and "
      f"job.py asks for {job.BROLL_SOURCE_TRIES}")
