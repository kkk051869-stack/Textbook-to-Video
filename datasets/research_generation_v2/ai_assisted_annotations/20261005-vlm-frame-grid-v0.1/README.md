# AI-assisted frame annotation set

This directory contains all 125 available neighbourhood-frame observations for
the 25 preselected Pilot v1 events (5 cases × 5 events × 5 offsets).

- Model: `qwen2.5-vl-32b-awq`
- Label scope: whether the supplied target was visibly observed in **one
  sampled screenshot**.
- `frame_grid_observations.json`: raw per-frame model responses and prompts'
  target metadata.
- `event_annotation_sheet.json`: event-level grouping of the five sampled
  observations.

These are `PROVISIONAL_AI_ASSISTED_NOT_HUMAN_GOLD`. They do not establish a
continuous object visibility interval, a correct visual target, an acceptable
pedagogical window, or an early/late semantic label. Those fields remain
explicitly unassigned rather than inferred from sparse samples.
