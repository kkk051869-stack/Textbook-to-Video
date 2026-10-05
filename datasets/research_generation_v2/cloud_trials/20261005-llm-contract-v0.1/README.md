# Cloud LLM contract trial

- Timestamp: 2026-10-05 (Asia/Shanghai)
- Remote host: `digital_book` (`/ai/data/use_ai_env.sh`)
- Endpoint: remote loopback `http://127.0.0.1:8000/v1`
- Model: `qwen3-32b-awq`
- Purpose: verify one real B-track proposition-to-element request can return the constrained JSON contract before a batch run.
- Not a formal result: one event only; no gold label; no aggregate metric; do not compare it with the lexical baseline.

## Input

| field | value |
|---|---|
| case | `lesson_002` |
| proposition | `s01-pc04`: “更是现代数字经济中解决信任问题的关键技术。” |
| candidate IDs | `lesson-002-seg-001-el-001` to `-003` |

Candidate elements were taken from the frozen Pilot v1 `segment_context.json`. The request required abstention when no direct teaching-semantic relation existed and limited targets to the supplied IDs.

## Raw constrained response

```json
{
  "status": "bound",
  "target_element_ids": ["lesson-002-seg-001-el-001"],
  "confidence": 0.9,
  "rationale": "命题中提到‘解决信任问题的关键技术’，与‘区块链：数字信任的基石’这一标题具有直接的教学语义关系。"
}
```

Usage returned by the server: 270 prompt tokens and 66 completion tokens. The response referenced only an allowed candidate ID and parsed as JSON. It does **not** establish semantic accuracy because no human/gold target is available for this proposition.
