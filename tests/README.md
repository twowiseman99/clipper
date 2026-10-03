# Regression tests

Run everything:

    bash tests/run_all.sh

Each `_vNN.py` is a bug that shipped a wrong clip. The filename is the render
version that exposed it. They are kept as separate scripts rather than merged
into a suite because each one documents a specific wrong assumption in its
docstring, and the docstring is the point — the code is small.

These tests invoke **real ffmpeg** and, for the b-roll gate, the **real vision
router**. That is deliberate. Every bug below passed a string-level assertion
first:

| test | what shipped wrong |
| --- | --- |
| `_v9` | b-roll source credibility: hoax/AI/game footage, view and date floors |
| `_v10` | caption/emphasis layout, reading order of the enlarged word |
| `_v11` | BGM mood matching, `_NEAR` substitutes and `_CLASH` forbidden pairs |
| `_v13` | the venue ("Gontor") was used as a cutaway trigger |
| `_v14` | outro colour ramp: `hue` has no `eval` option, ffmpeg refused the graph |
| `_v15` | burst cutaways — consecutive action words in one sentence |
| `_v16` | censor masking across Indonesian prefixes (`dibom`, `menyerang`) |
| `_v18` | `bgm.pick()` returns mood as a **list**, so a grief clip got the hype ending |
| `_v19` | window substance floors separate a busy frame from an empty wash |
| `_v20` | off-topic footage drops the whole source instead of falling back |
| `_v21` | b-roll band mask via `geq` on the alpha plane, framing unchanged |
| `_v22` | the action asked as its own question; aftermath is not the act |
| `_v23` | one rejected source must not cost the cutaway; zero b-roll must warn |
| `_v24` | a verified channel clears a lower view floor; `vetted(limit=1)` capped the shortlist |
| `_v25` | 8 finalists judged in parallel — the strike was never in the top 3 |
| `_v26` | the gate ran at temperature 0.2 and contradicted its own log |
| `_v27` | the gate is asked about the clip, once, not about each word |
| `_v28` | `on_topic` means **shot there**, not *about that* — a Jakarta rally shipped |

`_probe_broll.py` is not a test. It is the measurement tool used to decide
which frame signals are worth gating on; it prints rows, it asserts nothing.

## Rules these tests encode

- Footage must be real YouTube material of the place being discussed. A
  solidarity rally in another country is a reject, not a near-miss.
- A veto has no fallback: when every window fails, the clip ships with **no**
  cutaway and a warning, never a wrong cutaway.
- 1080x1920 and 9:16 are fixed. Any look is achieved with overlay layers, never
  by changing the canvas.
- A filter test must actually run ffmpeg. A test asserting on the filter string
  passes while ffmpeg refuses the graph.
