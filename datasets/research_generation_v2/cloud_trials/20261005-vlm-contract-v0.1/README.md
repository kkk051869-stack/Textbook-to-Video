# Cloud VLM contract trial

- Timestamp: 2026-10-05 (Asia/Shanghai)
- Remote host: `digital_book` (`/ai/data/use_ai_env.sh`)
- Endpoint: remote loopback `http://127.0.0.1:8001/v1`
- Model: `qwen2.5-vl-32b-awq`
- Purpose: verify a real frozen rendered frame can be sent to the cloud VLM and return a constrained, observation-only JSON result.
- Not a formal result: one frame only; it does not estimate object onset, offset, continuous visibility, or semantic-temporal correctness.

## Input

| field | value |
|---|---|
| case | `lesson_002` |
| event/frame | `1-a01`, center timestamp `0.0 s` |
| local frozen asset | `datasets/research_event_alignment/pilot_v1/cases/lesson_002/media/frames/1-a01/offset_+0.jpg` |
| query | whether the screenshot visibly contains content related to “区块链：数字信任的基石” |

The prompt explicitly restricted the model to visible screenshot evidence and required `temporal_claim: single_frame_only`.

## Raw constrained response

```json
{
  "visible": true,
  "visible_evidence": ["区块链：数字信任的基石"],
  "temporal_claim": "single_frame_only",
  "confidence": 1
}
```

Usage returned by the server: 2766 prompt tokens and 41 completion tokens. This establishes only that the VLM interface and an observation-only result contract work. It is not evidence of a rendered interval, and it must not be used to label an event `correct`, `early`, or `late`.
