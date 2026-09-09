from __future__ import annotations

import run_lesson001_judge_trial as judge


judge.INPUT_ROOT = judge.EXP_ROOT / "metrics/vlm/judge_inputs"
judge.OUTPUT_ROOT = judge.EXP_ROOT / "metrics/vlm/judge_outputs/formal_text_qwen32b_v1"
judge.PROMPT_VERSION = "judge_text_evidence_v2"
judge.JUDGE_RUN_ID = "formal_text_qwen32b_v1"


if __name__ == "__main__":
    judge.main()
