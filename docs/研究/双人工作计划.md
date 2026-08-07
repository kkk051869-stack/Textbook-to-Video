# Textbook-to-Video 与 PresentAgent 对照实验双人分工执行手册

> 适用实验：TextbookEval-v1 正式 8 课节对照实验  
> 适用人员：A、B 两名研究者  
> 当前原则：不做真人实验；不按课节机械平分；按“生成链路 / 对照与评价链路”并行推进  
> 数据集状态：若 `TextbookEval-v1` 已确认无问题，则从本文档开始进入实验执行阶段

## 1. 为什么采用这种分工

本实验有两条主要工作链路：

1. **生成链路**：把固定课节输入喂给 Textbook-to-Video，按实验条件批量生成视频、日志和中间产物。
2. **对照与评价链路**：让 PresentAgent 在同一批课节上生成外部对照结果，并用 annotation 对所有视频进行评价和统计。

如果简单按课节平分，例如 A 负责 4 课、B 负责 4 课，看起来平均，但实际会产生几个问题：

- 两个人都要分别搭建两套系统环境，重复成本高。
- 两个人生成的视频目录、日志格式和失败处理方式容易不一致。
- 评价标准可能被各自负责课节影响，后期很难统一。
- PresentAgent 与 Textbook-to-Video 的输入处理如果由两个人分别改，公平性更难保证。

所以更推荐采用**链路分工 + 交叉复核**：

| 角色 | 主责链路 | 辅助链路 | 核心交付 |
| --- | --- | --- | --- |
| A | Textbook-to-Video 生成链路 | 运行日志、失败案例、自动指标 | 内部系统 96 个视频及完整运行记录 |
| B | PresentAgent 对照与评价链路 | 数据集冻结、评分表、统计分析 | PresentAgent 8 个视频、评价表和实验结果 |

这样两个人不是“一个人跑、一个人等”，而是从第一天开始并行：

- A 一边打通和批量运行内部系统；
- B 一边打通 PresentAgent、冻结评价表、准备评分和统计模板；
- A 每产出一批视频，B 立即开始评价；
- B 每发现评价口径问题，A 根据日志确认是否属于系统问题。

## 2. 工作量是否平衡

这套分工不是按视频数量平衡，而是按**实际难度和耗时**平衡。

### 2.1 A 的工作量

A 的视频数量多，但大量工作可以脚本化。A 的主要压力在：

- 环境稳定；
- 批量运行；
- 中间产物完整保存；
- 失败原因定位；
- 生成条件不能混淆；
- 内部 2 × 2 实验配对必须严格一致。

A 需要产出：

- 48 次内部内容生成；
- 96 个内部视频；
- 每次运行的 script、storyboard、html、mp4、audio、log；
- 每个视频的运行状态和失败记录；
- 自动指标结果；
- 系统复现说明。

### 2.2 B 的工作量

B 的生成数量少，但人工判断和统计工作重。B 的主要压力在：

- PresentAgent 环境适配；
- 保证 PresentAgent 输入与内部系统公平；
- 把 annotation 转成可评分表；
- 评分时不能看错课节、条件或运行编号；
- 汇总双人评分差异；
- 写实验结果和分析。

B 需要产出：

- 8 个 PresentAgent 输出；
- 评价表模板；
- 每个视频的内容评分；
- 每个视频的图片使用评分；
- 每个视频的事实错误和遗漏记录；
- 双人评分差异表；
- 汇总统计和论文实验结果初稿。

### 2.3 平衡方式

为了让两个人工作量接近，采用以下补偿机制：

| 可能不平衡处 | 平衡办法 |
| --- | --- |
| A 跑内部视频数量更多 | A 主要用脚本批量跑；B 承担 PresentAgent 适配和评价体系 |
| B 人工评分耗时更长 | A 要提供完整日志、失败案例和自动指标，减轻 B 查证成本 |
| A 前期更忙 | B 前期同步做评分表、PresentAgent 最小运行和数据冻结 |
| B 后期更忙 | A 后期参与复核评分、整理失败案例和写复现部分 |

最终目标不是每天工作量完全一样，而是整个实验周期中两个人承担的有效工作接近。

## 3. 总体目录结构

建议所有实验产物放在云端数据目录，不放进 Git：

```text
/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/
├── sources/
│   ├── frozen/                 # 冻结后的生成输入；只能放 source.*、images、manifest、checksums
│   └── manifests/              # 数据集哈希、课节清单、冻结记录
├── private_annotations/
│   ├── B/                      # B 编写的 annotation 和保留题
│   └── gold/                   # 双方确认后的最终评价标准
├── runs/
│   ├── internal/               # Textbook-to-Video 内部系统输出
│   └── presentagent/           # PresentAgent 外部对照输出
├── ratings/
│   ├── A/                      # A 的独立评分
│   ├── B/                      # B 的独立评分
│   └── resolved/               # 讨论后确认的最终评分
├── metrics/
│   ├── automatic/              # 自动指标
│   ├── vlm/                    # 视觉语言模型辅助评价
│   └── statistics/             # 统计汇总
├── logs/
│   ├── internal/               # 内部系统运行日志
│   ├── presentagent/           # PresentAgent 运行日志
│   └── issues/                 # 失败案例和问题记录
└── reports/
    ├── daily/                  # 每日进度记录
    ├── tables/                 # 论文表格
    └── figures/                # 论文图
```

本地 Git 仓库只保存：

- 代码；
- 文档；
- 小型配置样例；
- 脚本；
- 评分表模板。

不要把 PDF、图片、生成视频、音频、HTML、运行输出打包进 Git。

## 4. 正式课节与实验对象

正式实验使用 8 个课节：

```text
lesson_001
lesson_002
lesson_004
lesson_005
lesson_007
lesson_008
lesson_011
lesson_012
```

正式实验材料拆成两类目录，不能混放。

生成输入目录：

```text
sources/frozen/{lesson_id}/
├── source.json
├── source.md
├── source.pdf
├── images/
├── manifest.json
├── package_check.json
└── checksums.sha256
```

私有评价目录：

```text
private_annotations/B/{lesson_id}/
└── annotation.json
```

生成输入目录里的每个课节包含：

- `source.json`：结构化教材内容；
- `source.md`：可读教材正文；
- `source.pdf`：给 PresentAgent 使用的课节 PDF；
- `images/`：教材图片；
- `manifest.json`：课节元信息；
- `checksums.sha256`：文件指纹。

重要规则：

- `source.*` 和 `images/` 可以给生成系统看；
- `annotation.json` 只能放在 `private_annotations/`，不能放进 `sources/frozen/`；
- 保留评价题不能进入 prompt、lesson plan、storyboard 或 PresentAgent 输入；
- 数据集冻结后，不能因为某个系统生成得不好而改 annotation。

## 5. A 的详细任务

A 的核心任务是让 Textbook-to-Video 按固定实验矩阵稳定产出。

### 5.1 A-1：确认内部系统环境

A 需要确认：

- 项目代码在正确分支或 tag；
- `.env` 已配置；
- `t2v doctor` 通过；
- ffmpeg 可用；
- 浏览器录制可用；
- TTS 可用；
- 输出目录不在 Git 仓库里。

建议记录到：

```text
logs/internal/environment_check.md
```

至少写明：

- 机器；
- 日期；
- Git commit；
- Python 版本；
- 依赖安装方式；
- 模型；
- TTS 声音；
- ffmpeg 版本；
- 浏览器版本；
- 是否通过最小样例。

### 5.2 A-2：准备内部实验矩阵

内部系统有两个内容分支：

| 分支 | 含义 |
| --- | --- |
| `P0` | 不使用教学计划 |
| `P1` | 使用教学计划 |

每个内容分支导出两个展示版本：

| 条件 | 内容分支 | 展示方式 |
| --- | --- | --- |
| `C00` | `P0` | 静态展示 |
| `C01` | `P0` | 定时逐步展示 |
| `C10` | `P1` | 静态展示 |
| `C11` | `P1` | 定时逐步展示 |

关键要求：

- `C00` 和 `C01` 必须来自同一个 `P0` 内容分支；
- `C10` 和 `C11` 必须来自同一个 `P1` 内容分支；
- 静态版只能关闭页内逐元素出现，不能重新生成讲稿、分镜、音频或图片；
- 定时版使用原始 `trigger_at_sec`；
- 每个内容分支正式重复 3 次，编号为 `r01`、`r02`、`r03`。

正式规模：

```text
8 课节 × 2 内容分支 × 3 次重复 = 48 次内部内容生成
48 次内容生成 × 2 个展示版本 = 96 个内部视频
```

### 5.3 A-3：内部输出命名

建议命名：

```text
runs/internal/{lesson_id}/{branch}/{repeat}/{condition}/
```

示例：

```text
runs/internal/lesson_001/P0/r01/C00/
runs/internal/lesson_001/P0/r01/C01/
runs/internal/lesson_001/P1/r01/C10/
runs/internal/lesson_001/P1/r01/C11/
```

每个条件目录至少包含：

```text
video.mp4
animation.html
run_config.json
run_status.json
```

每个内容分支目录至少包含：

```text
script.txt
storyboard.json
audio/
images/
content_generation.log
```

### 5.4 A-4：运行记录

A 每跑一次内容分支，都要记录：

| 字段 | 含义 |
| --- | --- |
| `lesson_id` | 课节编号 |
| `branch` | `P0` 或 `P1` |
| `repeat` | `r01`、`r02`、`r03` |
| `commit` | Textbook-to-Video Git commit |
| `model` | 使用模型 |
| `start_time` | 开始时间 |
| `end_time` | 结束时间 |
| `duration_sec` | 耗时 |
| `status` | `success`、`failed`、`partial` |
| `failure_stage` | 失败阶段 |
| `failure_reason` | 失败原因 |
| `output_path` | 输出路径 |

建议保存为：

```text
logs/internal/run_manifest.csv
```

### 5.5 A-5：失败处理

失败分成四类：

| 类型 | 例子 | 处理 |
| --- | --- | --- |
| 环境失败 | ffmpeg、浏览器、TTS 不可用 | 修环境后重跑，保留失败记录 |
| 输入失败 | 课节文件缺失、图片路径错误 | 与 B 确认是否数据集问题 |
| 生成失败 | LLM 超时、JSON 格式坏 | 允许按预设规则重试，记录重试次数 |
| 质量失败 | 视频生成成功但明显空白或布局崩坏 | 不直接丢弃，记录并进入评价 |

不能做的事：

- 不能因为某个结果不好就偷偷换 prompt；
- 不能只保留最好看的重复；
- 不能看完视频后选择质量最高的 `r02` 或 `r03` 当主结果；
- 不能修改数据集内容来适配系统。

正式评分默认使用 `r01`。如果 `r01` 因技术原因完全失败，使用第一个成功结果，并在日志里解释。

### 5.6 A-6：自动指标

A 负责优先计算这些自动指标：

- 是否成功生成 MP4；
- 视频时长；
- 页面数；
- 每页停留时间；
- 音频是否存在；
- 字幕是否存在；
- 图片文件是否被引用；
- 布局是否溢出；
- 页面是否空白；
- 元素出现时间误差；
- 运行耗时；
- 失败率。

输出到：

```text
metrics/automatic/internal_metrics.csv
```

## 6. B 的详细任务

B 的核心任务是让 PresentAgent 对照和评价体系同步推进。

### 6.1 B-1：冻结数据集

B 需要确认正式 8 课节的生成输入和私有评价材料：

- 每课生成输入目录都有 `source.json`、`source.md`、`source.pdf` 和 `images/`；
- 每课私有评价目录都有 `annotation.json`；
- 正文与课节主题一致；
- 图片 ID 可追踪；
- `annotation.json` 的 evidence paragraph 能支撑对应内容；
- core concepts 没有明显遗漏；
- heldout questions 能从教材推出；
- misconceptions 不牵强；
- 多图组图片要求合理。

冻结后输出：

```text
sources/manifests/dataset_freeze_record.md
sources/manifests/formal_lessons.csv
sources/manifests/checksums.sha256
```

冻结记录至少包含：

- 数据集版本；
- 正式课节列表；
- 备用课节列表；
- 每课文件哈希；
- 冻结日期；
- A/B 是否确认；
- 已知但接受的问题。

### 6.2 B-2：准备 PresentAgent 输入

PresentAgent 只能使用和内部系统等价的教材输入。默认输入：

```text
sources/frozen/{lesson_id}/source.pdf
```

B 需要确认：

- PDF 只包含该课节正文和教材图片；
- 不包含 annotation；
- 不包含 heldout questions；
- 不包含评分 rubric；
- 不包含任何为系统生成额外写的总结。

PresentAgent 输出目录：

```text
runs/presentagent/{lesson_id}/
```

每课至少保存：

```text
input.pdf
output.mp4
slides_or_html/
run_config.json
run_status.json
presentagent.log
```

### 6.3 B-3：PresentAgent 环境与运行记录

B 需要记录：

| 字段 | 含义 |
| --- | --- |
| `lesson_id` | 课节编号 |
| `presentagent_commit` | PresentAgent Git commit |
| `model` | 使用模型 |
| `input_pdf_sha256` | 输入 PDF 哈希 |
| `start_time` | 开始时间 |
| `end_time` | 结束时间 |
| `duration_sec` | 耗时 |
| `status` | `success`、`failed`、`partial` |
| `failure_reason` | 失败原因 |
| `output_path` | 输出路径 |

保存为：

```text
logs/presentagent/run_manifest.csv
```

### 6.4 B-4：建立评分表

B 把 annotation 转成评分表。评分表至少包含：

| 类别 | 评价内容 |
| --- | --- |
| 内容覆盖 | core concepts 是否被讲到 |
| 教材忠实度 | 是否背离教材、加入错误信息 |
| 图片使用 | required images 是否出现且解释正确 |
| 保留题支持 | 看完视频后是否能回答 heldout questions |
| 误解检查 | 是否出现 annotation 中列出的常见误解 |
| 教学结构 | 是否有清晰引入、展开、总结 |
| 视觉质量 | 画面是否清楚、布局是否正常 |
| 同步质量 | 画面元素是否配合旁白出现 |
| 完整性 | 视频是否完整、有声、可播放 |

建议评分文件：

```text
ratings/rating_template.xlsx
ratings/rating_template.csv
```

如果用 CSV，建议拆成几张表：

```text
ratings/templates/core_concept_scores.csv
ratings/templates/heldout_question_scores.csv
ratings/templates/image_scores.csv
ratings/templates/video_quality_scores.csv
ratings/templates/error_log.csv
```

### 6.5 B-5：评分规则

推荐使用 0/1/2 三档评分，便于双人一致：

| 分数 | 含义 |
| --- | --- |
| 0 | 没有覆盖、明显错误或无法判断 |
| 1 | 部分覆盖、有遗漏或表达不够清楚 |
| 2 | 准确覆盖、能支撑理解 |

对于事实错误，单独记录严重程度：

| 严重程度 | 含义 |
| --- | --- |
| `minor` | 小表述问题，不影响主结论 |
| `moderate` | 会造成局部误解 |
| `major` | 与教材核心内容相反或明显编造 |

对于图片：

| 分数 | 含义 |
| --- | --- |
| 0 | 应出现但没有出现，或出现错误图片 |
| 1 | 出现但解释弱、时机不佳或不够清楚 |
| 2 | 出现正确，且解释与正文对应 |

多图组特殊规则：

- lesson_007 不要求每张相似图都出现，但三类信任机制必须被覆盖；
- lesson_011 不要求 `fig7-2` 图组每一张都出现，但必须正确说明新四大发明和共享单车位置；
- lesson_012 没有教材图片，不因没有图片扣分。

### 6.6 B-6：统计分析

B 负责把评分结果整理成：

- 每个系统/条件的平均分；
- 每个课节的平均分；
- core concept 覆盖率；
- heldout question 正确支持率；
- 图片使用正确率；
- 事实错误数；
- 失败率；
- 平均生成时间；
- 内部系统四个条件之间的差异；
- 完整系统 `C11` 与 PresentAgent 的差异。

输出到：

```text
metrics/statistics/summary_tables.xlsx
metrics/statistics/summary_tables.csv
reports/tables/
reports/figures/
```

## 7. 双人交叉复核

虽然主链路不同，但评分必须交叉复核。

推荐方式：

| 任务 | A | B |
| --- | --- | --- |
| 主评分 | `lesson_001`、`lesson_002`、`lesson_004`、`lesson_005` | `lesson_007`、`lesson_008`、`lesson_011`、`lesson_012` |
| 复评分 | 复核 B 的 4 课 | 复核 A 的 4 课 |

每个人最终都至少看过 8 个正式课节的代表性结果，但完整主评分工作量对半分。

代表性结果默认包括：

- `C00 r01`
- `C01 r01`
- `C10 r01`
- `C11 r01`
- `PresentAgent`

也就是每课 5 个视频，8 课共 40 个视频用于人工主评价。

如果 `r01` 技术失败：

- 使用同条件下第一个成功重复；
- 在评分表里标注替代原因；
- 不允许按观感选择更好的重复。

## 8. 每日推进计划

下面是一个 7 天版本。实际可以压缩或拉长，但顺序不要乱。

### Day 1：冻结输入与最小运行

A：

- 确认 Textbook-to-Video 环境；
- 跑通 1 个课节的最小内部流程；
- 建立内部输出目录；
- 写 `environment_check.md`。

B：

- 冻结正式 8 课节；
- 建立数据集冻结记录；
- 确认 PresentAgent 能读取 1 个 `source.pdf`；
- 建评分表初版。

共同确认：

- 正式课节列表；
- 数据集版本；
- 输出目录结构；
- 命名规则。

### Day 2：试运行

A：

- 对 1 到 2 个课节跑内部 `P0/P1`；
- 导出静态版和定时版；
- 检查配对是否正确；
- 记录失败和耗时。

B：

- 对同样 1 到 2 个课节跑 PresentAgent；
- 用评分表试评 5 个代表性视频；
- 发现评分字段不清楚时修改评分表。

共同确认：

- 内部系统输出是否可评；
- PresentAgent 输出是否可评；
- 评分表是否够用；
- 是否进入正式运行。

### Day 3-4：正式生成

A：

- 跑 8 个正式课节的内部 48 次内容生成；
- 导出 96 个内部视频；
- 失败项按规则重试；
- 维护 `run_manifest.csv`。

B：

- 跑 8 个正式课节的 PresentAgent；
- 同步开始评分已经生成的视频；
- 检查每个视频是否能打开、有声、完整。

共同确认：

- 有没有数据集级别问题；
- 有没有必须暂停的系统级问题；
- 有没有命名或目录错误。

### Day 5：主评分

A：

- 主评前 4 个课节；
- 整理内部自动指标；
- 写失败案例初稿。

B：

- 主评后 4 个课节；
- 整理 PresentAgent 运行记录；
- 建统计脚本或统计表。

共同确认：

- 评分口径是否一致；
- 是否存在需要讨论的争议项。

### Day 6：复评分与争议解决

A：

- 复核 B 主评的 4 个课节；
- 补充工程指标和失败原因。

B：

- 复核 A 主评的 4 个课节；
- 合并双人评分；
- 输出评分差异表。

共同确认：

- 哪些评分取平均；
- 哪些评分需要讨论后定稿；
- 哪些视频因为技术失败不能纳入主分析。

### Day 7：统计与写作

A：

- 写系统运行、配置、复现、失败案例；
- 整理自动指标表。

B：

- 写数据集、评价方法、统计结果；
- 生成论文表格和图；
- 写主要结论草稿。

共同确认：

- 结果是否支持假设；
- 哪些结论只能谨慎表述；
- 哪些限制需要写进论文。

## 9. 交接规则

### 9.1 A 交给 B 的内容

A 每完成一批内部视频，应交给 B：

```text
run_manifest.csv
internal_metrics.csv
对应视频目录
失败记录
配置文件或配置摘要
```

B 不应该需要重新猜：

- 这个视频是哪一课；
- 是哪个条件；
- 是第几次重复；
- 有没有教学计划；
- 是静态版还是定时版；
- 是否技术失败后替代。

### 9.2 B 交给 A 的内容

B 每完成一批评价，应交给 A：

```text
评分表
错误案例清单
图片使用问题清单
争议项清单
统计初步结果
```

A 需要根据这些内容确认：

- 问题是系统真实缺陷，还是评分误解；
- 是否能从日志找到原因；
- 是否需要补充失败案例；
- 是否需要补充自动指标。

## 10. 冻结点

实验过程中必须设置冻结点，避免边做边改导致结果不可复现。

| 冻结点 | 冻结内容 |
| --- | --- |
| F1 | 正式 8 课节和备用课节 |
| F2 | 数据集文件与哈希 |
| F3 | annotation 和 heldout questions |
| F4 | 内部系统代码 commit 与配置 |
| F5 | PresentAgent 代码 commit 与配置 |
| F6 | 评分表字段与评分规则 |
| F7 | 正式运行矩阵 |
| F8 | 统计方法 |

冻结后允许修改的只有：

- 运行失败记录；
- 评分记录；
- 统计输出；
- 论文表述。

冻结后不允许随意修改：

- 教材正文；
- 图片；
- annotation；
- 评分题；
- 实验条件；
- 主结果选择规则。

## 11. 沟通节奏

建议每天只开两个短同步点：

### 上午同步

每人回答：

- 今天要完成什么；
- 需要对方提供什么；
- 有没有阻塞。

### 晚上同步

每人回答：

- 今天完成了什么；
- 新增了哪些文件；
- 哪些失败或异常；
- 明天是否需要调整计划。

不要把所有细节都放在聊天里，关键状态应写进文件：

```text
reports/daily/YYYY-MM-DD.md
logs/issues/issues.csv
```

## 12. 判断实验可以正式开始的清单

开始正式生成前，A/B 需要共同确认：

- [ ] 8 个正式课节已经冻结；
- [ ] 每课 `annotation.json` 已通过检查；
- [ ] `source.pdf` 能被 PresentAgent 使用；
- [ ] 内部系统至少 1 个课节完整跑通；
- [ ] PresentAgent 至少 1 个课节完整跑通；
- [ ] 内部系统的静态版和定时版配对正确；
- [ ] 输出目录和命名规则固定；
- [ ] 评分表已经用试运行视频试评过；
- [ ] 失败重试规则已经写清楚；
- [ ] 主结果选择规则已经写清楚；
- [ ] 两个人都知道自己当天要交付什么。

如果这些都满足，就可以进入正式实验。

## 13. 最推荐的当前下一步

如果现在数据集已经没有问题，下一步不要再继续扩数据集。建议立即做下面四件事：

1. B 冻结 `TextbookEval-v1` 正式 8 课节，生成哈希和冻结记录。
2. A 跑 `lesson_001` 的内部最小完整流程，确认能产出视频。
3. B 跑 `lesson_001` 的 PresentAgent 最小对照，确认外部系统可用。
4. A/B 用 `lesson_001` 的 5 个代表性视频试评一次，修正评分表。

这一步完成后，再批量跑 8 个正式课节。这样风险最小，也不会在评分阶段才发现前面的产物不可用。
