# Joint visual planning Spike — 2026-11-13

This is an isolated one-case engineering Spike. It does **not** modify the ordinary `produce` flow and does not establish a research-effectiveness claim.

## Input and planning

- Source: `datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/cases/lesson_002/source/source.pdf`, PDF page 1, section `（一）链式数据结构`.
- Source SHA-256: `0528282e74eda4b6f1562b80d971b235aab9e0ccaef9e2e38cf52a9d168aabdc`.
- The model jointly planned one proposition, four narration sentences, six knowledge nodes, four directed relationships, and sentence-level `focus_ids`.
- Model: `ecnu-plus`; two calls total. The first response failed exact source-substring validation because of PDF line wrapping; one bounded correction produced the saved second response. Token usage is unavailable from the existing client wrapper.
- The existing visual grammar and renderer were reused. One isolated, source-supported UTXO definition node was adapted to the renderer's existing footer slot; no relationship was invented for it.
- Local SAPI generated the narration. Measured audio duration: 34.764 seconds. No image generation, RQ1 decision, or Proposed v1.3 call was made.

## Result

- Voiced MP4: `joint-planning-spike.mp4` (H.264 1920×1080, AAC audio, subtitle stream; 34.77 seconds). Full FFmpeg decode completed successfully.
- Browser trace: 9/9 events executed (one `show`, eight `focus` subevents). This proves event execution, not teaching correctness.
- Keyframes are in `keyframes/`; static layout screenshots for 1366×768 and 1600×900 are in `layout-screenshots/`.
- The focus targets change across the four narration cues and map from planned node/relation IDs through SVG/DOM animation IDs. The second narration selected both input nodes but only one of the two input edges. It also mentions the 0.8 BTC total without an explicit total node/label in the visual.
- Each focus currently lasts 4.5 seconds, shorter than several sentence cues; focus therefore disappears before the narration sentence ends. The 32.5-second frame shows this during the last sentence.
- Layout checks found no clipping at the two static viewports, but the graph occupies a relatively small central area with substantial whitespace. Continuous human listening of the full audio was not performed.
- Recommendation: absorb joint object/focus planning locally; do not replace the old main flow based on this single case.

## Files and replay boundary

The folder includes the runner snapshot, prompt, both raw model replies, source manifest, generated plan/SVG/HTML, measured cues, runtime trace, layout report, final MP4, and reviewed screenshots. The original local run remains under `.local/data/runs/visual-planning-spike-20261113-01/`.

Large raw recorder intermediates (including approximately 48 MB of raw MJPEG frames) are intentionally not copied; the final MP4, runtime trace, and selected frames are retained. `run_spike.py` is an archival one-case runner, not a supported CLI or a production entrypoint. Do not run it in this committed evidence directory; it writes artifacts beside itself and depends on the local source PDF, SAPI voice, browser, and FFmpeg setup.

## Validation and Git scope

- Development preflight: passed; 33 targeted research checks passed. Preflight did not find FFmpeg/ffprobe on `PATH`; the configured local FFmpeg binary was used separately to decode the full MP4 successfully.
- No ordinary `produce`, production module, RQ1, or Proposed implementation was changed for this Spike.
- This branch is based on `8c325a9`, whose three unpushed ancestors (`ae2d7cd`, `e9be072`, `8c325a9`) provide the existing generated-SVG focus integration used by the Spike.
- `artifact-manifest.json` records SHA-256 and size for each archived artifact other than the manifest itself.
