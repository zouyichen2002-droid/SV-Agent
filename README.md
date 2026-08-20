# sv-bridge

**An agent orchestration layer over the Synthesizer V MCP runtime** — memory, retrieval, tool design, and staged evaluation gates for vocal covers and original composition.

> ### Relationship to upstream — please read first
>
> This is **not** a fork of, nor a replacement for, [`SynthVCopilot/synthv-agent-bridge`](https://github.com/SynthVCopilot/synthv-agent-bridge).
>
> That project (Apache-2.0) provides the **MCP runtime**: the six-tool surface, fingerprint-guarded writes, undo boundaries, and file-IPC transport into Synthesizer V Studio 2 Pro. It is consumed here as an unmodified dependency.
>
> **This repository is the layer above it**: orchestration, memory, retrieval, evaluation, and the domain workflows for cover reproduction and original songwriting. All credit for the runtime belongs upstream.
>
> *(Naming note: the similar name is coincidental. See the table below for who does what.)*

| Concern | Owner |
|---|---|
| MCP tool surface, guarded writes, undo boundaries, file IPC | upstream `synthv-agent-bridge` |
| Pipeline orchestration & staged quality gates | **this repo** |
| Memory (per-song state, tuning conventions, style preferences) | **this repo** |
| Retrieval over domain knowledge & prior work | **this repo** |
| Evaluation harness, benchmark cases, regression metrics | **this repo** |
| Musical/aesthetic judgment | the human |

---

## Status

**Early. Not usable yet.** Design and benchmark definition are complete; implementation has not started. See `HANDOFF.md` for the full engineering context and `specs/adr/` for decision records.

---

## Why this exists

Two goals, in order:

1. **Solve a real creative problem.** Producing vocal covers and original songs with Synthesizer V involves a long chain of mechanical work — transcription, lyric alignment, phoneme timing, pitch curves, expression parameters — that is tedious but highly structured. Good targets for an agent.
2. **Serve as a full-stack agent architecture exercise**, exercising MCP, tool design, memory, retrieval, orchestration, and evaluation against a domain where correctness is *measurable* rather than a matter of taste.

## Design principles

These came out of a failed first attempt (documented, see below). They are the point of the project, not decoration.

1. **Every stage has a numeric gate.** No stage advances until its criterion is met. The first attempt chained six inference steps with no verification and produced a regression dressed up as a 93% improvement.
2. **Never validate with the estimator you built with.** Notes derived from an f0 estimator cannot be scored by that same estimator. Cross-estimator agreement, or nothing.
3. **Refuse to guess.** Output only what has direct acoustic evidence. Report gaps explicitly instead of interpolating. In the first attempt, 21% of emitted notes were interpolated from neighbours — that fabrication *was* the audible defect.
4. **The human owns the last mile.** The system's job is to make the mechanical part trustworthy and to say clearly where it is uncertain.

## Benchmark & acceptance criteria

One Mandarin cover is used as the regression case. A passing cover pipeline must satisfy **all** of:

| Metric | Target | First attempt |
|---|---|---|
| Syllable alignment rate (direct, no interpolation) | ≥ 98% | 95.2% |
| Pitch accuracy, measured by an **independent** estimator | ≥ 85% within 0.5 semitone | 64.3% (grounded subset only) |
| Fabricated notes | **0** | 63 of 300 (21%) |
| Note geometry | 0 overlaps, all durations ≥ 85 ms | met |
| Human listening check | no audible lyric misalignment | **failed** |

The reference audio, stems, lyric files and project files for the benchmark are **not** in this repository (third-party copyright). Paths are supplied via local config.

## Architecture

```
        human  ──  direction, aesthetic judgment, final acceptance
          │
   ┌──────▼───────────────────────────────────────────┐
   │  sv-bridge   (this repo)                         │
   │    orchestration + staged gates                  │
   │    memory  ·  retrieval  ·  evaluation harness    │
   └──────┬───────────────────────────────────────────┘
          │ MCP over stdio
   ┌──────▼───────────────────────────────────────────┐
   │  synthv-agent-bridge   (upstream, Apache-2.0)     │
   │    six-tool surface, guarded writes, undo         │
   └──────┬───────────────────────────────────────────┘
          │ file IPC → resident Lua script
   ┌──────▼───────────────────────────────────────────┐
   │  Synthesizer V Studio 2 Pro                       │
   └───────────────────────────────────────────────────┘
```

## Layout

```
toolkit/            implementation
skills/             agent-facing runbooks
specs/              specifications
specs/adr/          decision records — why each choice was made, and what evidence would overturn it
eval/               benchmark cases and reports
scripts/            model fetch, environment setup
```

## Requirements

- Synthesizer V Studio 2 Pro ≥ 2.1.2 (developed against 2.2.1)
- Node.js ≥ 20.10 (for the upstream MCP runtime)
- Python 3.13
- An MCP host that speaks local stdio

## Licence

TBD for this repository's own code.

Third-party components retain their own terms:

- `synthv-agent-bridge` — Apache-2.0
- `SynthVCopilot/SKILLS` — Apache-2.0 + Commons Clause + additional terms. **Source-available, not open source.** Personal and internal commercial use permitted; redistribution as part of a paid product is not. Outputs produced with it are unrestricted.
- Acoustic models are downloaded at setup time and are not redistributed here.
