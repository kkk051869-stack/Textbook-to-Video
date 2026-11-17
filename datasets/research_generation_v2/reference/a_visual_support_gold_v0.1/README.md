# A visual-support human-reviewed gold v0.1

This directory contains the minimal, read-only 30-item A-track reference used
by `gold_alignment.py`.  It is evaluation input only and must never enter a
generation prompt, candidate pool, or lesson-plan input.

- Status: `FROZEN` / `HUMAN_REVIEWED_GOLD`
- Review status: `CONFIRMED_BY_USER`
- Items: 30
- Visual-support distribution: `none=28`, `source-sufficient=1`,
  `extra-support-needed=1`
- Retrieval distribution: `no=29`, `generation-candidate=1`
- Original local artifact SHA-256: `5e5b1dbd953eef0e5cf8a12ec7ec36a128c195b9b252f31c8af231ec29cb14de`
- Canonical JSON SHA-256 (UTF-8, sorted keys, compact separators):
  `d5ec065f116f5ab9fb668b81becfa0185a788e2cfeb989c8f15325d483342139`

The committed JSON is semantically identical to the reviewed local artifact.
Its raw byte hash differs because the local producer stored unusual one-line
whitespace; the canonical JSON hash above is stable across formatting and line
ending changes.

This small sample is strongly class-imbalanced.  It is suitable for pipeline
and baseline diagnostics, not for claims of external accuracy, inter-annotator
agreement, or method superiority.
