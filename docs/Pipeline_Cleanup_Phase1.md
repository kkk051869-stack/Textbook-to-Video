# Pipeline cleanup — phase 1

Branch: `refactor/pipeline-cleanup`.
Baseline: `origin/codex/workspace-snapshot-20261115`,
`46b50b7bbec13df9c4e6ed5583168741025adc1a`.

## Scope

Share the four generation entry points' lesson-plan generation/persistence,
script serialization, Storyboard serialization, audio-duration measurement,
and persistence of already-timed Storyboards. Keep entry-point orchestration,
parser selection, model calls, and compatibility policies in their existing places.
`pipeline/generation.py` contains ordinary functions, without a workflow framework.

The two old CLI commands share a separate `run_legacy_cli_tts` function. They do
not delegate to `orchestrator.run_tts`.

## Preserved differences

| Behavior | Legacy CLI | Orchestrator builders / run_tts |
| --- | --- | --- |
| Audio generation | Segment-level generate_audio, backend defaults | Existing backend, semantic/legacy selection, voice/rate, partial and frozen/reused audio logic |
| Measured duration precision | One decimal | Three decimals |
| Duration read failure | Integer 0 | Float 0.0 |
| Timing | apply_timing without explicit mode or cues | Existing explicit mode and validated sentence cues |
| Timed in-memory object | Replacement returned by apply_timing | Caller dictionary updated in place |
| DOCX script header | 第1段： | 第1： |
| PDF script header | Segment 1: | Segment 1: |
| Research v2 dual writes | None | Existing flag-controlled writes |
| DOCX metadata attachment | Existing metadata key required | setdefault retains historical tolerance |

The generic CLI `generate` command still selects its parser by file type and
uses lesson-style filenames, including for DOCX. Chapter/section extraction,
image propagation, title rules, review arguments, logging, CLI parameters,
output names, JSON indentation and newline behavior remain in place.

The unchanged generate_script and generate_storyboard functions already provide
shared generation algorithms. Their caller orchestration remains explicit to
avoid adding policy switches or changing prompts. P0, TextbookEval, animation,
recording and composition code are outside this change.

## Offline verification

Before production edits: 36 tests passed across generation compatibility,
narration, orchestrator and timing tests. The compatibility test contributes
12 fixed-input cases: four entry points, each with normal TTS, skipped TTS,
and a duration-reading failure. Parser, model generation, audio generation and
duration probes are replaced with deterministic in-process stubs.

After extraction: the same 36 tests passed. An additional one-off comparison
loaded the original CLI and orchestrator source directly from the baseline Git
objects, executed the same 12 cases against both implementations, and found
identical artifact bytes and stdout after replacing temporary output paths.

The related offline set (the above plus CLI argument tests, script continuation
tests and sentence-audio tests) passed all 74 tests. New helper and compatibility
test files passed Ruff; `git diff --check` passed.

## Limits

No real LLM, TTS, image generation, browser recording or full video pipeline was
run. These checks establish deterministic orchestration and artifact compatibility,
not final perceptual quality. Generic DOCX generation, malformed model output,
all environmental/backend combinations and every filesystem failure are not
exhaustively covered by the new fixed-input cases. Existing semantic and partial
narration tests provide additional coverage without changing those algorithms.

## Rollback

Compatibility tests and implementation are separate commits. The implementation
can be reverted independently, retaining the behavior baseline tests. No merge
or push to the Snapshot branch is part of this phase.
