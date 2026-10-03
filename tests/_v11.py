"""The anthem under the massacre.

v10 shipped mood "emotional" with `inspiring_giants_league.mp3` playing, because
an unstocked mood fell back to any track in the folder. The operator's note:
the whole video's music should be sad, not just the outro.

Offline — writes throwaway mp3 names into a temp dir, never touches the real
BGM folder.
"""
import os
import tempfile

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import bgm


def _stock(tmp, *names):
    for n in names:
        open(os.path.join(tmp, n), "wb").close()


with tempfile.TemporaryDirectory() as tmp:
    # The exact v10 situation: one inspiring track, a clip that is emotional.
    _stock(tmp, "inspiring_giants_league.mp3")
    track, why = bgm.pick("emotional", key="k", dirpath=tmp)
    assert track is None, f"anthem still chosen for a grief clip: {track}"
    assert "emotional" in why and "bgm_add" in why, why

    # The clip it IS right for still gets it.
    track, why = bgm.pick("inspiring", key="k", dirpath=tmp)
    assert track and "giants" in track["file"], (track, why)

with tempfile.TemporaryDirectory() as tmp:
    # A near mood is an acceptable stand-in, and is reported as a substitution.
    _stock(tmp, "mysterious_slow_strings.mp3")
    track, why = bgm.pick("emotional", key="k", dirpath=tmp)
    assert track, why
    assert "mysterious" in why and "no 'emotional'" in why, why

with tempfile.TemporaryDirectory() as tmp:
    # An exact match beats a near match.
    _stock(tmp, "emotional_piano.mp3", "mysterious_slow.mp3")
    track, why = bgm.pick("emotional", key="k", dirpath=tmp)
    assert "emotional_piano" in track["file"], (track, why)
    assert "no 'emotional'" not in why, why

with tempfile.TemporaryDirectory() as tmp:
    # Comedy music must never land under a tense clip either.
    _stock(tmp, "funny_kazoo.mp3")
    track, why = bgm.pick("tense", key="k", dirpath=tmp)
    assert track is None, (track, why)
    track, why = bgm.pick("emotional", key="k", dirpath=tmp)
    assert track is None, (track, why)

with tempfile.TemporaryDirectory() as tmp:
    # An unknown mood is a config problem, not a clash: take anything rather
    # than dropping the music.
    _stock(tmp, "hype_drums.mp3")
    track, why = bgm.pick("nonsense-mood", key="k", dirpath=tmp)
    assert track, why
    assert "unknown mood" in why, why

with tempfile.TemporaryDirectory() as tmp:
    # Empty folder is still the plain no-tracks answer.
    track, why = bgm.pick("emotional", key="k", dirpath=tmp)
    assert track is None and "no tracks" in why, why

# Clash table sanity: the pairs that caused this must stay blocked, and no mood
# may list a clashing substitute.
assert bgm._clashes("emotional", "hype")
assert bgm._clashes("emotional", "inspiring")
assert not bgm._clashes("emotional", "mysterious")
for mood, alts in bgm._NEAR.items():
    for alt in alts:
        assert alt in bgm.MOODS, (mood, alt)
        assert not bgm._clashes(mood, alt), f"{mood} lists clashing {alt}"

print("_v11.py OK — emotional clip refuses the inspiring anthem "
      "(stock-only), accepts mysterious/chill, prefers an exact match")
