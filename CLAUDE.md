# Clipper — working notes

Project #1 of **Oden Tal Company**. Studio charter, divisions, and the ship
gate live in `docs/ODEN_TAL_COMPANY.md` — read it before taking on new scope.

## Deploy convention (standing rule)

Every deploy ships with release notes. Add the release to `RELEASE_NOTES.md`
before pushing the deploy, and sign it **Dalmislave**. Notes state what changed,
what it costs, and — importantly — what is still broken, since that is what
decides whether the pipeline can be left running unattended.

## Shape of the thing

`pipeline.py` is the hourly loop (crawl → fetch → transcribe → select → render →
upload). `job.py` is the agent-facing entry point: two links in, one clip and a
JSON result out. `edit.py` is the renderer and holds nearly all the visual
constants — they were measured off reference clips, and the numbers are in the
comments beside them.

Three ways in, cheapest first:

    python edit.py preview FOOTAGE --hook "..."   # one local file, no services
    python job.py --list                          # catalogue, JSON
    python pipeline.py --dry-run                  # whole chain, uploads nothing

## Before implementing anything new (standing rule)

Check the installed skills first and say which ones apply and which do not.
They exist because each one encodes a mistake already made on this project.

| Doing | Read first |
|---|---|
| Hook, title, description copy | `short-video-hook-research` |
| Cuts, transitions, visual polish | `short-video-editing-grammar` |
| Any content/topic decision | `content-trend-research` |
| Changing Python | `python-review-and-qa` |
| About to say "done"/"fixed" | `verification-before-completion` |
| Multi-step feature | `writing-plans`, then `brainstorming` |
| Acting on review feedback | `receiving-code-review` |

Rule: load the skill only when it changes what you do. Naming a skill without
following it is worse than not loading it, because it implies a check happened.
State plainly when a skill adds nothing to the task at hand.

Source repos are mirrored at `~/skill-sources/` (superpowers, agency-agents,
gstack, awesome-agent-skills) for pulling further material without re-cloning.

## Tuned settings (what the knobs are set to and why)

These live in `.env` on the box. Recorded here because the values are decisions,
not defaults: each one is the result of watching a rendered clip and changing it.

| Setting | Value | Why |
|---|---|---|
| `CLIPPER_PAN` | `0` | Camera movement was distracting on talking-head footage. |
| `ZOOM_CYCLE` | `12` | One slow zoom per ~12s; faster reads as a wobble. |
| `CLIPPER_CAPTION_STYLE` | `editorial` | Plate alpha 215 + 3px stroke for legibility. Karaoke kept. |
| hook font | `64` | Larger wrapped to three lines and hit the UI band. |
| `CLIPPER_EMPH_THRESHOLD` | `1.15` | Tunes how many words `emphasis.py` uppercases. |

Two traps worth knowing before you restyle captions:

- The enlarged word must be the **last** word of its phrase. Anywhere else and
  the reading order scrambles, because the big word pulls the eye first.
- BGM runs at 80% through the hook, then ducks to 20% under speech with a 0.6s
  fade. B-roll audio is muted in the hook so two voices never overlap.

BGM files live at `/home/ubuntu/background_music/<mood>_<name>.mp3`, added with
`bgm_add.py --mood X <url>`.

## House rules

- Every module has a `__main__` self-check. Run the ones you touched; they are
  the test suite.
- A dry run must consume nothing: no `clips` row, no `segment_usage` row, and
  the task goes back to `DISCOVERED`.
- Secrets stay out of the repo (`.env`, `cookies.txt`, `clippo_session.json`,
  `tokens/`). `preflight.py` reports which are missing.
- Anything drawn on the frame must clear the platform UI band at the bottom.
  Anchor overlays by their bottom edge so a longer wrap grows upward.

<!-- antislop:start -->
## antislop

For UI, copy, people, mobile layout, or code comments work, read
`.claude/skills/antislop/SKILL.md` (core) and then the skill for the task:

- UI / visual: `.claude/skills/antislop-ui/SKILL.md`
- Copy & text: `.claude/skills/antislop-copywriting/SKILL.md`
- People: `.claude/skills/antislop-human/SKILL.md`
- Mobile / responsive: `.claude/skills/antislop-layoutmobile/SKILL.md`
- Code comments: `.claude/skills/antislop-code/SKILL.md`

Before starting, ask the user when antislop applies: during the work, or after
it is done.

### Where the line falls in this repo

The core bans the em dash "in any text" (R-02). Here that means the text this
project **ships**: hooks, titles and descriptions drawn on a clip or posted with
it, and anything the dashboard renders. Python comments, docstrings and
`RELEASE_NOTES.md` are internal prose; `antislop-code` governs those and says
nothing about dashes, so leave them alone rather than churning the whole tree.

`metadata.py` enforces the shipping half in code, because a prompt constraint is
a request and the model can still ignore it: connector dashes are replaced, and
a figure the transcript never states is dropped before it reaches the frame.
Adding a rule to the prompt without an enforcement path is half a fix.

There is no `DESIGN.md`. The dashboard's palette is not invented taste: it reuses
`edit.py`'s `QUOTE_TEAL` and `PHRASE_COLOR`, both measured off the reference
clips, so the console and the clips look related. Anything new that needs
direction should extend that, or ask.

Verify contrast, never estimate it:

    python3 .claude/skills/antislop-human/contrast-check.py "#EDE9E1" "#12100E"
<!-- antislop:end -->
