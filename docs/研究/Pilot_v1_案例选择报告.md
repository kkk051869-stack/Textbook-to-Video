# Pilot v1 案例选择报告

> 选择原则：coverage / representativeness，而不是预先知道某案例能证明研究假设。  
> 候选池：`datasets/pilot3/` 的 8 个真实 lesson，以及对应历史 eval run 中的 runtime trace 与 final MP4。  
> 最终样本：5 个 lesson。

## 1. 候选池

| case | source | segments | elements | runtime events | renderer evidence | signaling actions | runtime trace | MP4 | source evidence | 选择 |
|---|---|---:|---:|---:|---|---|---|---|---|---|
| lesson_001 | 数字化转型：实现路径 | 7 | 43 | 43 | template；归档运行记为 deterministic | show | AVAILABLE；3 target missing | AVAILABLE | 17 段、2 图 | 否 |
| lesson_002 | 区块链：信任数据库 | 10 | 65 | 65 | 1 页声明 `llm`、9 页 template；归档运行仍记为 deterministic/no fallback | show、highlight | AVAILABLE；无 target missing | AVAILABLE | 15 段、1 图 | **是** |
| lesson_004 | 数字经济：我国发展数字经济的优势 | 9 | 57 | 57 | template；deterministic | show、pulse、highlight | AVAILABLE；无 target missing | AVAILABLE | 10 段、1 图 | **是** |
| lesson_005 | 大数据：数据是新的生产要素 | 10 | 60 | 60 | template；deterministic | show、highlight | AVAILABLE；无 target missing | AVAILABLE | 20 段、1 图 | 否 |
| lesson_007 | 区块链：信任体系 | 8 | 50 | 50 | template；deterministic | show | AVAILABLE；1 target missing | AVAILABLE | 21 段、7 图 | **是** |
| lesson_008 | “东数西算”工程：比拟性解读 | 7 | 46 | 46 | template；deterministic | show | AVAILABLE；无 target missing | AVAILABLE | 15 段、1 图 | 否 |
| lesson_011 | 区块链：共享单车 | 9 | 52 | 52 | 1 页声明 `llm`、8 页 template；归档运行仍记为 deterministic/no fallback | show | AVAILABLE；无 target missing | AVAILABLE | 18 段、6 图 | **是** |
| lesson_012 | “东数西算”工程：逻辑性解读 | 9 | 60 | 60 | template；deterministic | show | AVAILABLE；5 target missing | AVAILABLE | 10 段、0 图 | **是** |

说明：候选池中没有 `focus` 或 `dim` action。`lesson_002` 与 `lesson_011` 的 storyboard 含声明为 `llm` 的 segment，但归档 candidate manifest 记录 `deterministic_renderer=true`、`llm_fallback_used=false`，因此本报告不把它们宣称为已确认的真实 LLM-rendered 页面。

## 2. 最终选择

### lesson_002

- 覆盖 10 个 segment 和当前最大 element/event 密度之一；
- 包含真实 `highlight` action；
- 有完整 source、runtime trace 和 MP4；
- runtime target 全部解析成功，可作为正常技术执行案例；
- 含声明为 `llm` 的页面，可检查声明模式与实际归档 renderer evidence 的差异。

### lesson_004

- 候选池中唯一同时包含 `pulse` 与 `highlight` 的案例；
- visual type 包含 definition、data-bar、data-chart、process 与 illustration；
- runtime target 全部成功，适合观察 signaling applicability，而不是只观察技术失败。

### lesson_007

- 具有候选池中最多的教材图片之一（7 张），适合 Visual Correctness 与 source support 判断；
- 包含 comparison 与 activity 页面；
- 有 1 个技术 target missing，使样本同时覆盖正常 case 与 technical issue，但该错误不会自动转成教学违规。

### lesson_011

- 有 6 张 source image、70 个 proposition candidates，是 source/visual binding 的高信息量案例；
- 含 closing 与声明为 `llm` 的页面；
- runtime target 全部成功，避免样本只由失败案例构成。

### lesson_012

- source 没有教材图片，但 storyboard 有 comparison、process 与 illustration，形成与图片丰富案例的对照；
- 有 5 个 target missing，覆盖资源/DOM 技术缺失风险；
- 选择它是为了证据形态覆盖，不是因为 target missing 能证明教学违规。

## 3. 未选中的高价值案例

| case | 高价值点 | 本轮未选原因 |
|---|---|---|
| lesson_001 | 两张教材图、3 个 target missing | template/show-only 与 lesson_007、lesson_012 的覆盖重复；在 5 案容量上限下优先保留 source-image 更多的 lesson_007 和无图对照 lesson_012 |
| lesson_005 | 10 segments、2 个 highlight、20 个 source paragraphs | highlight 已由 lesson_002/004 覆盖；source/image 形态与已选案例重合。保留为扩展池，不因质量好坏排除 |
| lesson_008 | process/comparison 页面、技术执行正常 | show-only，且视觉/source 形态由 lesson_004/012 覆盖；保留为 taxonomy 扩展或替补案例 |

## 4. 覆盖结果

最终 5 案共同覆盖：

- 45 segments；
- 284 elements；
- 284 runtime events；
- 277 raw timeline items；
- `show`、`highlight`、`pulse`；
- source image 从 0 到 7 张；
- 技术执行正常与 target missing 两类；
- definition、illustration、comparison、process、data chart、activity、closing 等页面类型；
- 每案均有 source、narration、HTML、runtime trace 和 final MP4。

该选择不保证存在任何教学原则违规，只保证人工 pilot 有足够多样的客观证据可检查。
