"""A generic casualty word is not a declaration of war.

The Gibran clip rejected 37 frames and shipped zero cutaways. The ledger said
"no footage passed the gates", which reads as "no usable footage exists". The
brief, newly printed, said something else:

    GIVEN act required  the attack itself or its immediate destruction:
    strikes, explosions, smoke over buildings, shelling, collapsed or burning
    buildings, rubble, wounded or dead being carried

A clip about children poisoned by a school meal was under a war-footage veto,
so every frame of Gibran at a hospital in Karo was correctly rejected for not
showing shelling. The trigger was one word: "korban", which in Indonesian means
the victim of anything at all — korban keracunan, korban banjir, korban PHK.

The veto has no fallback, so over-strictness shows up as NO b-roll rather than
worse b-roll. That is the third time that shape has appeared, and each time the
fix was to find the wrong UNIT rather than loosen a threshold.

Offline, no network, no ffmpeg.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import job


def words(text, start=10.0):
    out, t = [], start
    for w in text.split():
        out.append({"word": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
        t += 0.4
    return out


# --- the clip that broke: casualties, no violence ---------------------------
gibran = words("Saya mewakili pemerintah menyampaikan permohonan maaf kepada "
               "orang tua siswa yang menjadi korban keracunan MBG di Karo . "
               "Seluruh biaya perawatan korban ditanggung pemerintah .")
assert job._clip_act(gibran) == "", \
    "a food-poisoning clip still demands war footage"

# --- the clip the gate exists for: must still demand war footage ------------
palestina = words("Saudara-saudara kita di Palestina . Mereka dibantai . "
                  "Mereka dibom . Mereka diserang terus-menerus .")
look = job._clip_act(palestina)
assert look, "the war clip lost its veto"
assert "strikes" in look and "rubble" in look, look

# --- a casualty word NEXT TO a violence word keeps the veto -----------------
# This is the case that must not regress: "korban" is harmless alone, but the
# clip is still a war clip when something real is named too.
mixed = words("Ada banyak korban setelah serangan itu .")
assert job._clip_act(mixed), "violence named alongside 'korban' lost the veto"

# --- each demoted word, alone, is not a war clip ----------------------------
for w in ("korban", "tewas", "meninggal", "kelaparan"):
    txt = f"Banyak yang {w} akibat kelalaian panitia ."
    assert job._clip_act(words(txt)) == "", f"{w!r} alone triggered war footage"

# --- each hard word, alone, IS a war clip -----------------------------------
for w in ("dibantai", "bantai", "dibom", "bom", "pemboman", "diserang",
          "serang", "serangan", "dibunuh", "hancur", "reruntuhan", "gugur"):
    txt = f"Mereka {w} di sana ."
    assert job._clip_act(words(txt)), f"{w!r} no longer triggers war footage"

# --- the trap words stay out, as before -------------------------------------
# Substring matching would catch all three. These are the negative controls
# that caught an earlier version of this list.
for w in ("serangga", "serangkaian", "bombardir"):
    txt = f"Ada {w} di kebun belakang ."
    assert job._clip_act(words(txt)) == "", f"{w!r} was read as violence"

# --- the two sets must not overlap ------------------------------------------
# A word in both would make the hard list win silently and the soft list a lie.
overlap = job._ACT_WORDS & job._ACT_SOFT
assert not overlap, overlap

# --- empty input ------------------------------------------------------------
assert job._clip_act([]) == ""
assert job._clip_act(None) == ""

print("_v33 ok — 'korban' alone no longer demands war footage; "
      "Palestina clip keeps its veto")
