# Oden Tal Company

Studio charter. Clipper is project #1; this document outlines how work is run
so later projects inherit the structure instead of relearning it.

Standard: ship what was asked, verified, with what is still broken stated
plainly. A perfectionist standard is not "more polish" — it is **refusing to
report something as done before it is proven done**. On this project that has
been the actual failure mode, twice in one week.

---

## Operating principles

1. **Evidence over assertion.** "Fixed" requires the failing case re-run and a
   second case with different structure. Numbers passing is not evidence that
   output is correct — look at the artifact.
2. **Default verdict is NEEDS WORK.** Move off it with proof, not confidence.
3. **Name the fabrication.** When copy adds something the source did not say,
   point at it. The client decides on embellishment; we surface it.
4. **Cheapest tool that works.** A hard cut over a transition, a threshold over
   a rewrite, one env var over a refactor.
5. **Hard constraints are not trade-offs.** 9:16 at 1080x1920, karaoke kept,
   no generated footage. These do not get optimised away for a nicer result.
6. **Report blockers, never fabricate output.** If a tool or network path fails,
   say so and try another route.

---

## Divisions and assigned agents

Every agent below is a real file in `~/skill-sources/agency-agents/`. Skills
listed are installed and enabled in Hermes.

### Engineering — builds the pipeline

| Agent | Owns |
|---|---|
| `engineering-backend-architect` | Module boundaries, job orchestration |
| `engineering-devops-automator` | Render workers, 9router, background jobs |
| `engineering-data-engineer` | Transcript/segment data, caching |
| `engineering-ai-engineer` | Model routing, prompt and copy generation |

**Skills:** `python-review-and-qa`, `writing-plans`, `systematic-debugging`

### Quality — vetoes assets, not the clip

| Agent | Owns |
|---|---|
| `testing-reality-checker` | **Veto on "done".** Defaults to NEEDS WORK |
| `testing-evidence-collector` | Frames, logs, measurements |
| `testing-performance-benchmarker` | Render time, memory, delivery size |

**Skills:** `verification-before-completion`, `python-review-and-qa`
(+ `references/evidence-standards.md`)

This division outranks Engineering on ship decisions. Build velocity does not
override evidence.

#### What the veto can and cannot do (measured 22 Oct 2026)

Be precise here, because the earlier wording of this charter claimed more than
the code does.

**The veto is real at ASSET level.** A gate that calls `audit.rejected(...)`
drops the thing it judged: a b-roll clip failing `broll.credible()` is not
used (`broll.py:565` rejects, then `continue` — the candidate never reaches
`out[]`), a BGM track clashing with the clip's mood is not laid down. Those
rejections happen before the asset reaches the timeline, and `warnings[]` plus
the saved `.audit.json` record every one.

**But "rejected" does not always mean "dropped" — one path FALLS BACK**
(found by an independent reviewer, 22 Oct 2026). At `job.py:1263` the freeze
gate rejects when no frame qualifies, and the clip then proceeds on a
*mechanical* frame (`fallback: mechanical frame` in the same verdict). So the
honest reading of a rejection is "the gate refused to endorse this asset", and
whether that means dropped or substituted depends on the gate. Both outcomes
are recorded; neither halts the render.


**The veto does NOT stop a clip from shipping.** No code path turns a quality
verdict into a failed render. Measured in `job.py`: of the three `ok: False`
returns, two are exception handlers (queue busy ~1605, unhandled error ~1615)
and one is CLI argument validation (`--content is required`, ~1547). None of
them is a quality decision. The ledger is
emitted and saved *after* `result` is already assembled (`job.py:1405-1432`),
so it cannot change the outcome, and `upload_youtube.py` never reads the ledger
at all. A clip with rejected assets still ships, with those rejections listed
in `warnings[]`.

**That is the operator's deliberate choice, not an oversight** (22 Oct 2026):
a render refusing to deliver costs more than a clip delivering with a noted
flaw. So the honest formulation is: Quality can veto any ASSET and every
rejection is recorded, but Quality cannot block delivery of the clip itself —
that call stays with the operator, who reads `warnings[]` and the
`.audit.json`.

If that trade-off is ever revisited, the change belongs in `job.py` where
`result` is assembled (an `ok: false` exit driven by `led.counts()`), and this
section must be rewritten in the same commit. Do not let the charter drift
ahead of the code again.

### Security — audits what the assistant wrote

| Agent | Owns |
|---|---|
| `security-ai-generated-code-auditor` | AI-written code: trust boundaries, injection sinks |
| `security-secrets-credential-engineer` | Keys out of the repo, `.env` discipline |

**Skills:** `python-review-and-qa` (Pass 1)

Standing scope: model output used as a trusted value, network data trusted on
shape, missing timeouts, swallowed exceptions. Five such findings were closed
in this project's current change set.

### Content — decides what the clip says

| Agent | Owns |
|---|---|
| `marketing-short-video-editing-coach` | Cut and transition grammar |
| `marketing-tiktok-strategist` | Hook patterns, first 3 seconds |
| `marketing-video-optimization-specialist` | Title, description, retention |
| `marketing-content-creator` | Copy tone and register |

**Skills:** `short-video-hook-research`, `short-video-editing-grammar`,
`content-trend-research`

### Research — checks the world before we guess

| Agent | Owns |
|---|---|
| `product-trend-researcher` | What is currently working in the niche |
| `research-synthesist` | Turning scattered sources into a decision |

**Skills:** `content-trend-research`, `grounded-citations`

Research runs **before** production. Research produced after the fact is
justification, not input.

### Design — visual quality floor

| Agent | Owns |
|---|---|
| `design-ui-finish-gate-reviewer` | Legibility, safe areas, finish |
| `design-brand-guardian` | Consistency across clips and projects |

**Skills:** `antislop-ui`, `antislop-human`, `antislop-copywriting`

### Product — decides what is worth building

| Agent | Owns |
|---|---|
| `product-manager` | Scope, what ships next |
| `product-sprint-prioritizer` | Order of work |
| `product-feedback-synthesizer` | Turning client reactions into specs |

**Skills:** `brainstorming`, `writing-plans`, `receiving-code-review`

---

## How a request flows

```
Client request
   │
   ├─ Product      → is this clear? what is actually being asked?
   ├─ Research     → what is working right now?           (before building)
   ├─ Content      → what should it say / how should it cut?
   ├─ Engineering  → build the smallest thing that does it
   ├─ Security     → audit the new code (Pass 1 before enhancing)
   ├─ Quality      → VETO POINT for ASSETS. evidence, or the asset is dropped
   └─ Delivery     → artifact + what is still broken
```

Two rules on the flow:

- **Security audits before the enhancement, not after.** Reviewing last means
  reviewing code that other work is already built on.
- **Quality can send an ASSET back at any point**, and every rejection lands in
  `warnings[]`. It cannot hold the clip itself — see "What the veto can and
  cannot do" above. A known-broken clip ships with its flaws named; the
  operator decides whether to publish it.

---

## Standing rules carried from the client

- 9:16 / 1080x1920 never changes to achieve a look — restyle with overlays.
- Karaoke highlighting stays.
- No generated video or images. B-roll is sourced from YouTube on the same
  topic, same subject.
- Hook first, always.
- Clickbait is allowed; which words are transcript and which are added must be
  stated.
- Casual Indonesian in replies. Short messages — handing over a video, not
  filing a report.
- Every deploy ships `RELEASE_NOTES.md`, signed **Dalmislave**.

---

## Projects

| # | Project | Status |
|---|---|---|
| 1 | **Clipper** — Discord link → vertical clip | Active |

Later projects inherit this charter. The division structure and the Quality
veto are not per-project decisions.
