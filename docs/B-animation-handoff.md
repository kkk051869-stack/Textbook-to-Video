# B Animation Handoff

本文档对应分支 `codex/animation-runtime-v2`，用于 A 负责人消费 B 的动画计划、浏览器 trace 和指标。本文档不新增公共 Schema，也不包含 Compiler rejected-event diagnostics。

## 1. Animation event 输入格式

Compiler 的标准输出是每个 slide 一个 event 数组。正式 Schema 要求以下 9 个字段，当前 Compiler 不输出额外字段。

| 字段 | 类型 | 必填 | 默认值 | 说明 / 错误行为 |
| --- | --- | --- | --- | --- |
| `event_id` | string | 是 | `slide_id-aNN` | 多 target 展开时追加 `-1`、`-2`；空值自动生成 |
| `slide_id` | string | 是 | 无 | Compiler 将 segment id 转为 string |
| `target` | string | 是 | 无 | 必须是安全 ID；未知但非空的 target 会保留为 unresolved 事件 |
| `selector` | string | 是 | `[data-anim-id="target"]` | Runtime 用它查询 DOM；无匹配时 trace 为 `target_missing` |
| `action` | enum | 是 | `show` | `show/highlight/dim/focus/draw/grow/move`；其他 action 被 Compiler 拒绝并告警 |
| `effect` | string | 是 | 按 action 推导 | `show=fadeInUp`、`highlight=highlight`、`dim=fadeIn`、`focus=highlight`、`draw=drawPath`、`grow=growBar`、`move=legacy` |
| `start_ms` | integer >= 0 | 是 | 无 | 来自 `start_ms`、`at_ms` 或秒字段；缺少时间的 event 不编译，负值钳制为 0 |
| `duration_ms` | integer >= 0 | 是 | `600` | 支持 `duration_ms`、`duration_sec`、`duration`；负值钳制为 0 |
| `easing` | string | 是 | `ease-out` | 写入 Runtime CSS timing function |

旧 Storyboard action 兼容归一：`pulse` 编译为 `highlight + pulse`，`fadeOut` 编译为 `show + fadeOut`，因此不会产生不符合 v2 enum 的 event。`transform`、`counter`、`typeWrite` 当前不属于本阶段 action。

一个实际编译 event 示例：

```json
{
  "event_id": "s01-a02-1",
  "slide_id": "s01",
  "target": "e2",
  "selector": "[data-anim-id=\"e2\"]",
  "action": "highlight",
  "effect": "pulse",
  "start_ms": 1500,
  "duration_ms": 900,
  "easing": "linear"
}
```

`timeline[].target` 支持逗号分隔的 multi-target。Compiler 为每个 target 生成独立 event；`stagger: true` 时默认相邻 event 间隔 `200ms`，可用 `stagger_ms` 覆盖，显式 `0` 也会保留。

## 2. `animation_trace.json`

浏览器运行后可通过：

```js
window.downloadAnimationTrace()
```

下载 `animation_trace.json`。文件根节点直接是数组，与 `window.animationTrace` 内容一致，不包含 summary 或 issues。

每条 trace 字段如下：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `event_id` | string | 对应计划 event |
| `slide_id` | string | 发生 event 的 slide |
| `target` | string | 计划 target |
| `action` | string | 计划 action |
| `effect` | string | 计划 effect |
| `planned_ms` | number | 相对当前 slide 动画开始时间的计划触发时间 |
| `duration_ms` | number | 计划动画时长 |
| `easing` | string | 计划 easing |
| `actual_ms` | number/null | Runtime 实际触发或结束状态记录时间；仍为 scheduled 时可为 null |
| `status` | string | 当前状态，见下表 |
| `error` | string/null | 失败或取消原因 |

当前 status：

- `scheduled`：已注册 timer，尚未到触发时间
- `executed`：已找到目标并执行 action/effect
- `target_missing`：selector 没有匹配 DOM
- `unsupported_action`：action/effect/move 条件不支持；具体原因在 `error`
- `runtime_error`：Runtime 查询或执行发生异常
- `cancelled`：页面切换清除了尚未执行的 timer

真实 trace 示例：

```json
[
  {
    "event_id": "s01-a01",
    "slide_id": "s01",
    "target": "e1",
    "action": "show",
    "effect": "fadeInUp",
    "planned_ms": 0,
    "duration_ms": 600,
    "easing": "ease-out",
    "actual_ms": 5,
    "status": "executed",
    "error": null
  },
  {
    "event_id": "s01-a02",
    "slide_id": "s01",
    "target": "e9",
    "action": "show",
    "effect": "fadeInUp",
    "planned_ms": 1000,
    "duration_ms": 600,
    "easing": "ease-out",
    "actual_ms": 1003,
    "status": "target_missing",
    "error": "No element matched [data-anim-id=\"e9\"]"
  },
  {
    "event_id": "s01-a03",
    "slide_id": "s01",
    "target": "e7",
    "action": "move",
    "effect": "legacy",
    "planned_ms": 2000,
    "duration_ms": 600,
    "easing": "ease-out",
    "actual_ms": 2001,
    "status": "unsupported_action",
    "error": "unsupported_move:requires data-flip-id and data-step"
  },
  {
    "event_id": "s01-a04",
    "slide_id": "s01",
    "target": "e8",
    "action": "show",
    "effect": "fadeInUp",
    "planned_ms": 3000,
    "duration_ms": 600,
    "easing": "ease-out",
    "actual_ms": 120,
    "status": "cancelled",
    "error": "Animation timer cancelled"
  }
]
```

## 3. B 提供的指标

指标实现位于 `src/textbook2video/animation_metrics.py`，输入是编译 event 数组和 `animation_trace.json` 数组。

| 指标 | 计算口径 |
| --- | --- |
| `target_resolution_rate` | `status ∈ {executed, unsupported_action}` 的 event 数 / 全部已编译 event 数 |
| `effect_realization_rate` | 实际 `executed` 且 trace 的 action/effect 与计划一致的 event 数 / action 和 effect 均在 B 支持范围内的计划 event 数 |
| `unsupported_action_count` | `status=unsupported_action` 且 error 不是 `unsupported_effect:*` 的数量 |
| `unsupported_effect_count` | `status=unsupported_action` 且 error 以 `unsupported_effect:` 开头的数量 |
| `runtime_error_count` | `status=runtime_error` 的数量 |
| `timing_mae_ms` | 有效 executed event 的 `mean(abs(actual_ms - planned_ms))` |
| `unobserved_event_count` | 没有在 trace 中找到对应 `event_id` 的已编译 event 数 |

`target_resolution_rate` 的分母包含已经进入 Compiler 的 unresolved target。它们会保留为合法 event，并在 Runtime 产生 `target_missing`，不会因为找不到 DOM 就从分母消失。

Compiler 直接拒绝的非法 action 没有进入编译 event 数组，因此当前不会进入上述分母。如果 A 希望把这类 action 纳入计划总数或失败率，需要新增 diagnostics 接口。

## 4. A/B 需要确认的接口

| 问题 | B 当前行为 | B 建议 | A 是否需要确认 |
| --- | --- | --- | --- |
| `move` 是否维持当前 Schema | 正式 action enum 已包含 `move` | 保持当前 Schema | 是 |
| `move` 的 DOM 语义 | Runtime 依赖目标元素的 `data-flip-id` 和 `data-step`，使用现有 FLIP 逻辑 | 将这两个属性作为 move 的正式 DOM 约定 | 是 |
| `cancelled` 是否进入正式 trace status | 页面切换时清除未执行 timer，并写入 `cancelled` | 纳入正式 trace status | 是 |
| timeline 与旧 `animations` 优先级 | 非空 timeline 优先；timeline 编译为空时回退旧 `animations`；无 timeline 时保留 data-step fallback | 固化该兼容优先级 | 是 |
| multi-target 展开规则 | 一个 target 一个 event，ID 追加 `-1/-2` | 保持 | 是 |
| stagger 展开规则 | 默认 `200ms`，支持 `stagger_ms`，输出只保留展开后的 `start_ms` | 保持，不把 stagger 字段加入 event Schema | 是 |
| 默认 duration | `600ms` | 固化公共默认值 | 是 |
| 默认 easing | `ease-out` | 固化公共默认值 | 是 |
| `animation_trace.json` 根节点 | 直接使用 trace 数组 | A 直接消费数组 | 是 |
| Compiler rejected action | 当前只告警并跳过，不生成 trace event | 如需计入计划失败率，再设计 diagnostics | 是 |

## 5. 正式 3 Case 验收步骤

B 不自行选择 frozen Case。A 提供三个 Case 后，每个 Case 至少需要：

1. frozen storyboard JSON；
2. 所有本地图片/SVG 资源及其相对路径；
3. baseline HTML 或 baseline 生成方式；
4. Case 名称、commit、主题和运行参数；
5. 若需要 LLM fallback，对应模型和可用凭据。

以下步骤在 B worktree 根目录执行。示例使用 `case-01`，其余 Case 同样运行。

### 5.1 生成 B HTML

```powershell
$case = "D:\cases\case-01"
$after = "$case\after"
python -m textbook2video.cli animate "$case\storyboard.json" `
  --output "$after" --theme bright --repair 0 --browser ""
```

输出通常为：

```text
$after\storyboard-pipeline-bright.html
```

`--repair 0` 用于保留本次原始生成结果；如果正式验收要求与日常 pipeline 一致，应记录并固定 `--repair` 参数。`--browser ""` 使用 Playwright 默认 Chromium；也可以改成 A 环境可用的 `msedge` 或 `chrome` channel。

### 5.2 运行 layout check

```powershell
python scripts/check_layout.py `
  "$after\storyboard-pipeline-bright.html" `
  --width 1920 --height 1080 --wait-ms 2200 `
  --json "$after\layout-1920x1080.json" --browser-channel ""

python scripts/check_layout.py `
  "$after\storyboard-pipeline-bright.html" `
  --width 1366 --height 768 --wait-ms 2200 `
  --json "$after\layout-1366x768.json" --browser-channel ""
```

正式结果应保存两个 viewport 的 JSON，不要只看终端摘要。

### 5.3 真实浏览器运行并导出 trace

当前没有额外的 Eval Harness。可以在 PowerShell 中执行下面这个最小 Playwright runner；它只打开 HTML、切换每个 slide、等待该页计划 event、下载原始 trace，并调用 B 的指标函数：

```powershell
@'
import json, os, sys
from pathlib import Path
from textbook2video.animation_gen import build_slide_timelines
from textbook2video.animation_metrics import compute_animation_metrics
from playwright.sync_api import sync_playwright

html_path = Path(sys.argv[1]).resolve()
storyboard_path = Path(sys.argv[2]).resolve()
output_dir = Path(sys.argv[3]).resolve()
output_dir.mkdir(parents=True, exist_ok=True)
storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
segments = storyboard["segments"]
plans = build_slide_timelines(segments)
plan = [event for timeline in plans for event in timeline]

def executable(playwright):
    configured = os.environ.get("T2V_PLAYWRIGHT_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    default = Path(playwright.chromium.executable_path)
    if default.is_file():
        return str(default)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cached = sorted(Path(local).glob("ms-playwright/chromium-*/chrome-win/chrome.exe"), reverse=True)
        if cached:
            return str(cached[0])
    return None

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=executable(playwright))
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(html_path.as_uri(), wait_until="load")
    for index, timeline in enumerate(plans):
        if index:
            page.evaluate("index => window.SlideController.go(index)", index)
            page.wait_for_timeout(700)
        wait_ms = max([1000] + [int(event.get("start_ms", 0)) + 300 for event in timeline])
        page.wait_for_timeout(wait_ms)
    with page.expect_download() as info:
        page.evaluate("window.downloadAnimationTrace()")
    info.value.save_as(str(output_dir / "animation_trace.json"))
    browser.close()

trace_path = output_dir / "animation_trace.json"
trace = json.loads(trace_path.read_text(encoding="utf-8"))
metrics = compute_animation_metrics(plan, trace)
(output_dir / "animation_metrics.json").write_text(
    json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(metrics, ensure_ascii=False, indent=2))
'@ | python - `
  "$after\storyboard-pipeline-bright.html" `
  "$case\storyboard.json" `
  "$after"
```

交付给 A 的 B 原始证据为：

```text
$after\animation_trace.json
$after\animation_metrics.json
```

### 5.4 Before/After 数据

对三个 frozen Case 使用完全相同的输入、viewport、主题和运行参数：

```text
case-01/
  baseline/
    baseline.html
    layout-1920x1080.json
    layout-1366x768.json
  after/
    storyboard-pipeline-bright.html
    layout-1920x1080.json
    layout-1366x768.json
    animation_trace.json
    animation_metrics.json
```

记录：

- baseline 与 after 的 git commit
- 生成命令和浏览器 channel
- 两个 viewport 的 layout JSON
- after 的原始 animation trace 和 B metrics
- 三个 Case 的相同输入校验结果

B 不生成 A 的 `summary.csv` 或 `issues.csv`。baseline 如果没有 `window.animationTrace`，B 不会伪造 baseline trace；A 应提供 baseline 证据或明确只做 layout/视觉 Before/After。

## 6. 当前 B 状态

当前纯 B 代码、Compiler、Runtime、浏览器 E2E 和指标输入均已完成，没有阻塞正式 3 Case 的纯 B 内部问题。下一步等待：

1. A 提供三个 frozen Case 及 baseline；
2. A 确认本页接口表中的公共约定；
3. 再执行三 Case 的统一 Before/After 验收。
