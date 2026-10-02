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

### Quality — decides whether it ships

| Agent | Owns |
|---|---|
| `testing-reality-checker` | **Veto on "done".** Defaults to NEEDS WORK |
| `testing-evidence-collector` | Frames, logs, measurements |
| `testing-performance-benchmarker` | Render time, memory, delivery size |

**Skills:** `verification-before-completion`, `python-review-and-qa`
(+ `references/evidence-standards.md`)

This division outranks Engineering on ship decisions. Build velocity does not
override evidence.

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
   ├─ Quality      → VETO POINT. evidence, or it does not ship
   └─ Delivery     → artifact + what is still broken
```

Two rules on the flow:

- **Security audits before the enhancement, not after.** Reviewing last means
  reviewing code that other work is already built on.
- **Quality can send it back at any point.** There is no deadline that
  outranks a known-broken clip.

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
