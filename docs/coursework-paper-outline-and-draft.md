# 多Agent审核与模板渲染驱动的教材教学视频生成系统

> 课程论文初稿，按《计算机科学与探索》写作模板组织。  
> 待补信息：作者姓名、学院/专业/班级、学号、指导教师、课程名称。  
> 当前演示系统产物：`output\real_chapter_agent_review_test_v6_syncfix\lesson13.mp4`。

## 写作决策备注

### 0. 已读取的写作材料

用户提供了3个Word文档：

```text
C:\Users\echo\Downloads\20260123103641.docx
C:\Users\echo\Downloads\20211209135210.doc
C:\Users\echo\Downloads\20240919142726.doc
```

当前读取情况：

- `20260123103641.docx` 已成功读取，内容是《计算机科学与探索》论文写作模板。已确认要求包括：
  - 论文需包含中英文题名、作者信息、中英文摘要、关键词、正文和参考文献。
  - 中文摘要建议不少于400字，内容应说明研究目的、方法、结果和结论。
  - 摘要中不出现参考文献，不使用“本文”“作者”等作主语，尽量采用第三人称叙述。
  - 英文摘要应与中文摘要对应，尽量不用第一人称。
  - 正文采用顺序编码制引用参考文献。
  - 正文结构可包括引言、一级标题、二级标题、结束语、参考文献等。
  - 图表需有中英文图题、表题。
  - 参考文献需按模板格式著录，中文参考文献原则上提供英文对照。
- `20211209135210.doc` 是参考文献著录格式材料。用户已复制完整规范，已按复制内容整理如下。
- `20240919142726.doc` 是摘要编写规范材料。用户已复制完整规范，已按复制内容整理如下。

对本文写作的影响：

- 摘要会按“目的—方法—结果—结论”组织，避免自我评价。
- 英文摘要不使用第一人称，不写`In this paper`。
- 参考文献暂按GB/T 7714顺序编码制写，后续可再逐条核对作者、会议、页码和访问日期。
- 图表标题应补中英文双语标题。

### 0.1 摘要编写规范

科技论文摘要主要包括研究目的、方法、结果和结论。摘要应具有独立性和自明性，使读者不阅读全文也能获得必要信息。

中文摘要要求：

- 客观、如实反映论文内容，不加入主观见解、解释或评论。
- 排除本学科领域已成为常识的内容，不把应放在引言中的研究背景写入摘要。
- 未来计划不写入摘要。
- 采用第三人称写法，不使用“本文”“作者”“我们”“笔者”等作为主语。
- 可采用“对……进行了研究”“报告了……现状”“进行了……调查”等记述方法。
- 避免言过其实的表述，例如“极大改进”“首次实现”“经检索尚未发现”等。
- 一般不出现数学式、插图、表格和参考文献，尽量少用特殊字符。
- 非公知公用的简称和英文缩略语首次出现时应给出中文全称和英文全称。
- 字数原则上与论文成果相适应，最好不少于400字。

英文摘要要求：

- 英文摘要应与中文摘要内容对应。
- 不使用“It is reported…”“The author discusses…”“In this paper”等不必要表达。
- 尽量不用“in detail”“briefly”“here”“new”“mainly”等无实质信息修饰词。
- 减少Background Information，只保留新情况和新内容。
- 摘要第一句避免与题目重复。
- 摘要时态建议用一般现在时。
- 不随便省略冠词，尤其是定冠词“the”。
- 能用名词或形容词作定语时，尽量不用动名词作定语。
- 可直接用名词或名词短语作定语时，少用of句型。
- 可用动词时尽量避免使用动词的名词形式。
- 组织句子时，使动词尽量靠近主语。

本初稿摘要检查：

- 中文摘要已按“目的—方法—结果—结论”组织。
- 中文摘要中没有参考文献、图表和公式。
- 中文摘要仍需在最终排版前压缩或扩展到约400字以上，目前字数基本满足模板建议。
- 英文摘要没有使用第一人称，也没有使用“In this paper”。
- 英文摘要后续可根据最终中文摘要再做逐句对应润色。

### 0.2 参考文献著录格式

参考文献采用 `GB/T 7714-2015`。

常用文献类型：

| 文献类型 | 标志代码 |
|---|---|
| 图书 | M |
| 会议录 | C |
| 报纸 | N |
| 期刊 | J |
| 汇编 | G |
| 学位论文 | D |
| 报告 | R |
| 标准 | S |
| 专利 | P |

电子文献类型：

| 类型 | 标志代码 |
|---|---|
| 数据库 | DB |
| 计算机程序 | CP |
| 电子公告 | EB |

载体类型：

| 载体 | 标志代码 |
|---|---|
| 磁带 | MT |
| 磁盘 | DK |
| 光盘 | CD |
| 联机网络 | OL |

常用著录格式：

```text
专著：
主要责任者.题名：其他题名信息[文献类型标识/文献载体标识].其他责任者.版本项.出版地：出版者，出版年：引文页码[引用日期].获取和访问路径.

专著中的析出文献：
析出文献主要责任者.析出文献题名[文献类型标识/文献载体标识].析出文献其他责任者//专著主要责任者.专著题名：其他题名信息.版本项.出版地：出版者，出版年：析出文献的页码[引用日期].获取和访问路径.

连续出版物中的析出文献：
析出文献主要责任者.析出文献题名[文献类型标识/文献载体标识].连续出版物题名：其他题名信息，年，卷（期）：页码[引用日期].获取和访问路径.

专利文献：
专利申请者或所有者.专利题名：专利号[文献类型标识/文献载体标识].公告日期或公开日期[引用日期].获取和访问路径.

电子文献：
主要责任者.题名：其他题名信息[文献类型标识/文献载体标识].出版地：出版者，出版年（更新或修改日期）[引用日期].获取和访问路径.
```

责任者著录规则：

- 同一文献责任者不超过3人时全部照录。
- 超过3人时只著录前3人，后加“等”；外文用“, et al”，`et al`不必用斜体。
- 责任者之间用“，”分隔。
- 用汉语拼音书写的人名，姓全大写，名可缩写，取每个汉字拼音首字母。
- 欧美著者姓全部著录，字母全大写，名缩写为首字母并省略缩写点，采用姓前名后的形式。

版本著录规则：

- 第1版不著录。
- 其他版本用阿拉伯数字、序号缩略形式或其他标志表示，例如`3版`、`5th ed.`、`2005版`。

期刊年卷期页码规则：

```text
2005, 10(2): 15-20
2005, 35: 123-129
2005(1): 90-94
2005(1/2): 40-43
2005(10/11/12): 65-70
```

对本文参考文献的处理：

- PresentAgent 已有会议论文出处，按会议论文 `[C]//` 著录。
- SlideTailor 已有AAAI 2026论文信息，但页码可能后续需核对；若最终无法确认页码，可暂按电子文献 `[EB/OL]` 或无页码会议论文处理。
- Playwright、FFmpeg、W3C等在线文档按电子文献 `[EB/OL]` 著录，并给出引用日期。

### 1. 作者与课程信息

作者姓名、学院、专业、班级、学号、课程名称和指导教师先留占位，后续由人工补充。

### 2. 篇幅控制

作业要求论文篇幅不超过4页，因此正文应按“短论文/系统设计报告”压缩，避免写成完整毕业论文式长文。建议篇幅分配如下：

| 部分 | 建议篇幅 | 写作重点 |
|---|---:|---|
| 题名、作者、摘要、关键词 | 0.5页以内 | 交代系统目标、方法和结果 |
| 引言 | 0.5页 | 说明教材视频生成需求与现有方法不足 |
| 系统架构 | 0.8页 | 用图说明流水线和模块 |
| 关键技术 | 1.2页 | 写教学计划、Agent审核、模板渲染、音画同步 |
| 系统演示与结果 | 0.8页 | 写真实章节、运行步骤、输出产物 |
| 结束语 | 0.3页 | 总结贡献和后续改进 |
| 参考文献 | 0.3页 | 保留最相关文献 |

压缩原则：

- 不展开过多代码细节，代码细节放系统README或附录。
- 不逐条描述所有测试目录，只保留最终成品路径。
- 关键技术控制在4个小节以内。
- 结果部分用表格和1张截图提高信息密度。

### 3. 图表选择

建议放图，但不要放太多。4页限制下，最多使用2张图和1张表。

优先级最高：

1. 系统总体架构图。  
   必放，因为作业要求明确要求描述系统体系架构。图中可展示：

   ```text
   教材 → 解析 → Lesson Plan → Script → Storyboard → Agent Review → HTML动画 → 录制合成 → MP4
   ```

2. 最终视频截图或Storyboard预览截图。  
   建议放，用于证明系统确实有可运行演示，而不是只写概念。

3. 系统模块与功能表。  
   如果版面允许保留；如果超过4页，可以删表保留两张图。

推荐组合：

```text
图1 系统总体架构
图2 真实章节生成视频截图
表1 系统主要模块与功能
```

如果版面非常紧，则保留：

```text
图1 系统总体架构
图2 真实视频截图
```

### 4. 题目选择

当前初稿题目为：

```text
多Agent审核与模板渲染驱动的教材教学视频生成系统
```

这个题目能突出技术点，但略显概念堆叠。考虑到模板提示题名不宜过长，且课程设计论文更重视“系统做了什么”，建议改为更稳的题目。

推荐题目一，最稳妥：

```text
教材教学视频自动生成系统的设计与实现
Design and Implementation of an Automatic Textbook Teaching Video Generation System
```

优点：

- 简洁清楚。
- 符合课程设计论文风格。
- 老师能直接看出系统目标。
- Agent审核、模板渲染、音画同步可以放在摘要和关键技术里突出。

推荐题目二，稍微突出创新：

```text
融合多Agent审核的教材教学视频自动生成系统
Automatic Textbook Teaching Video Generation with Multi-Agent Review
```

优点：

- 比题目一更突出本文特色。
- 比“多Agent审核与模板渲染驱动……”更自然。

当前建议：

- 如果希望稳妥交作业，用题目一。
- 如果希望突出与普通教材转视频系统的区别，用题目二。
- 不建议最终题名继续使用“多Agent审核与模板渲染驱动的……”，因为标题技术词较多，适合作为正文创新点而非论文题名。

## 一、论文大纲

题名：多Agent审核与模板渲染驱动的教材教学视频生成系统  
英文题名：Textbook Teaching Video Generation with Multi-Agent Review and Template Rendering

摘要结构：

1. 研究目的：解决教材内容转教学视频时人工制作成本高、LLM直接生成画面不稳定、音画同步难的问题。
2. 方法：构建“教材解析—教学计划—讲稿—storyboard—TTS—HTML动画—录制合成”的流水线，引入多Agent审核与确定性模板渲染。
3. 结果：真实章节生成11页教学视频，Agent审核通过，最终成片时长261.1 s，输出MP4、字幕、HTML和质量报告。
4. 结论：系统能完成教材到有声动画视频的端到端生成，多Agent审核与时长驱动录制提升了可控性和可交付性。

关键词：

教材视频生成；多Agent审核；模板渲染；教学设计；音画同步

正文结构：

引言：说明教材视频制作需求、现有自动演示系统的不足、本文工作。

1 系统总体架构  
1.1 教材到视频的流水线  
1.2 教学计划与storyboard中间表示  
1.3 演示系统运行环境

2 关键技术  
2.1 教学计划驱动的内容组织  
2.2 Storyboard生成与质量增强  
2.3 多Agent审核与返修机制  
2.4 模板渲染与HTML动画生成  
2.5 TTS时长驱动的录制同步

3 系统演示与结果分析  
3.1 演示章节与运行步骤  
3.2 输出结果  
3.3 质量检查与问题修复  
3.4 与相关系统的差异

4 结束语

参考文献：采用顺序编码制。

建议插图：

- 图1 系统总体架构
- 图2 Storyboard Agent审核闭环
- 图3 真实章节演示流程
- 表1 系统主要模块与功能
- 表2 真实章节输出结果

## 二、论文初稿

题名：多Agent审核与模板渲染驱动的教材教学视频生成系统

作者名：XXX  
单位：XXX学院，XXX大学，城市 邮政编码

摘  要：针对教材章节难以快速转化为有声动画教学视频的问题，对教材教学视频自动生成方法进行了研究，设计并实现了一个面向PDF和DOCX教材的端到端生成系统。系统以教材章节文本和教材图片为输入，按照教材解析、教学计划生成、讲稿生成、结构化故事板（storyboard）生成、文本转语音配音、HTML动画渲染、浏览器录制和音画合成的流程生成MP4教学视频。方法上，在讲稿和画面生成之间引入教学计划层，用于组织教学目标、知识点、活动和检测题；采用结构化故事板描述每页画面的旁白、页面类型、元素列表和动画触发信息；在故事板生成后设置质量增强和多智能体审核环节，由生成智能体、审核智能体和修复智能体检查并处理标题复读、页面内容过少、图片引用异常、测验结构不完整和动画目标错误等问题；在动画生成阶段采用模板渲染优先、模型兜底的策略，将常见教学页面转换为可控HTML结构；在录制阶段依据文本转语音得到的真实音频时长控制页面切换，使画面进度与旁白分段保持一致。真实章节实验以“教育数字化转型”内容为对象，生成了包含11页画面、字幕和配音的教学视频，最终成片时长为261.1 s，同时输出HTML、故事板、字幕文件和质量报告等中间产物。实验结果表明，该系统能够完成从教材章节到有声教学视频的自动化生成，教学计划、结构化故事板、多智能体审核和时长驱动录制能够增强生成流程的可检查性和过程可控性。

关键词：教材视频生成；多Agent审核；模板渲染；教学设计；音画同步

Title: Textbook Teaching Video Generation with Multi-Agent Review and Template Rendering

Author: XXX

Abstract: Producing textbook-based teaching videos usually requires content summarization, script writing, slide design, animation authoring, narration recording and video editing, which makes the workflow costly and difficult to scale. A textbook teaching video generation system is designed and implemented to convert PDF or DOCX textbooks into narrated animated videos. The system contains a complete pipeline, including textbook parsing, lesson planning, script generation, storyboard generation, text-to-speech narration, HTML animation rendering, browser recording and audio-video composition. To reduce the instability of directly generating complex pages with large language models, a lesson-plan layer and a structured storyboard representation are introduced to explicitly organize knowledge points, teaching activities, assessment questions and visual elements. After storyboard generation, deterministic quality enhancement and a multi-agent review loop are used to detect and repair title-body repetition, thin pages, hallucinated image sources, incomplete quiz cards and invalid animation targets. During animation generation, common teaching pages are rendered by templates, while unsupported pages fall back to model generation. The final recording is driven by measured TTS durations, so that slide transitions can be aligned with narration segments. A real-chapter experiment generates an 11-slide teaching video with narration, subtitles, HTML animation and quality reports. The final video lasts 261.1 seconds. Experimental results show that the system can complete an end-to-end textbook-to-video workflow and improve controllability through multi-agent review and deterministic template rendering.

Key words: textbook video generation; multi-agent review; template rendering; instructional design; audio-video synchronization

教材内容向视频化教学资源转化是数字化教学中的常见需求。传统制作流程通常依赖教师或设计人员先阅读教材，再人工提炼知识点、撰写讲稿、制作课件、录制旁白并剪辑视频。该流程虽然能够保证较高的教学质量，但制作周期较长，不利于面向大量教材章节的快速生成。近年来，大语言模型和多模态生成技术推动了自动摘要、课件生成和演示视频生成的发展。PresentAgent能够将长文档转化为带旁白的演示视频，并强调视觉内容与语音内容的同步[1]；SlideTailor则关注科学论文到幻灯片的个性化生成，使生成结果能够适配用户偏好和模板风格[2]。这些工作说明了自动演示内容生成的可行性，但在面向教材教学场景时，仍需要进一步处理教学活动组织、知识点检测、画面结构稳定性和音画同步等问题。

针对上述问题，本文设计并实现了一个教材教学视频生成系统。系统以教材文件为输入，以有声MP4教学视频为输出，重点解决三个问题：第一，如何把教材正文转化为面向教学的讲解结构，而不仅是文本摘要；第二，如何避免大语言模型生成的页面出现标题和正文重复、内容单薄、图片引用幻觉等问题；第三，如何使页面切换和元素动画尽量与真实旁白时长一致。围绕这些目标，系统引入教学计划层、结构化storyboard、多Agent审核闭环和模板优先的HTML动画渲染方法，并在真实章节上完成了系统演示。

### 1 系统总体架构

系统整体流程如图1所示。输入端支持PDF和DOCX格式教材。系统首先对教材进行解析，抽取章节文本和可用教材图片；随后调用大语言模型生成教学计划，明确本节课的教学目标、知识点、活动设计和检测题；在此基础上生成讲稿分段，并进一步转化为结构化storyboard。每个storyboard segment对应视频中的一页画面，包含旁白文本、页面类型、元素列表、动画信息和知识点绑定。之后，系统使用文本转语音模块生成每页旁白音频，并测量真实音频时长。动画生成模块将storyboard渲染为单文件HTML，浏览器录制模块按页面时长录制无声视频，最后由音视频合成模块将分段音频、字幕和画面合成为MP4成片。

图1  系统总体架构  
Fig.1  Overall architecture of the system

系统主要模块见表1。

表1  系统主要模块与功能  
Table 1  Main modules and functions of the system

| 模块 | 输入 | 输出 | 功能 |
|---|---|---|---|
| 教材解析 | PDF/DOCX | 章节文本、图片清单 | 抽取教材内容与插图 |
| 教学计划 | 章节文本 | lesson plan JSON | 生成教学目标、知识点、活动和检测题 |
| 讲稿生成 | 文本、教学计划 | script | 生成分段旁白 |
| Storyboard生成 | script、图片清单 | storyboard JSON | 生成页面结构与视觉元素 |
| Agent审核 | storyboard | 审核结果、返修storyboard | 检查结构质量并自动返修 |
| 动画渲染 | storyboard | HTML | 模板渲染或模型兜底生成动画页面 |
| 录制合成 | HTML、音频 | MP4 | 浏览器录制并合成有声视频 |

### 2 关键技术

#### 2.1 教学计划驱动的内容组织

教材直接转讲稿容易退化为章节摘要，难以体现教学过程。为增强教学性，系统在讲稿和storyboard之前增加lesson plan层。该层记录教学目标、知识点、活动设计和检测题，使后续生成过程能够围绕教学结构展开。例如，在真实章节“教育数字化转型”的演示中，lesson plan为系统提供了概念区分、数据赋能、教育科技要素、课堂活动和知识点检测等信息。后续storyboard会根据这些信息生成“想一想”“知识点检测”“本节小结”等页面，从而使视频更接近教学设计，而不仅是教材摘要。

#### 2.2 Storyboard生成与质量增强

Storyboard是系统的核心中间表示。每页storyboard包含`visual_type`、`narration`、`elements`和`animations`等字段。`elements`中可以包含标题、正文、图片、图标组、流程步骤、对比面板和测验卡片等结构化元素。与直接让模型生成HTML相比，结构化storyboard更便于检查、修改和复用。

在真实测试中，模型直接生成的storyboard曾出现标题与正文重复、页面内容过少、图片路径幻觉、动画目标与元素ID不一致等问题。为此，系统加入确定性质量增强步骤，自动删除标题复读内容，为内容偏薄页面补充正文或主视觉结构，并刷新动画目标，确保动画只指向真实存在的元素。对于已经具备`icon_group`等主视觉元素的页面，系统会避免再加入冗余的`comparison_panel`，降低页面拥挤程度。

#### 2.3 多Agent审核与返修机制

为进一步提高生成结果的稳定性，系统设计了多Agent审核闭环，如图2所示。Storyboard生成Agent负责根据讲稿生成初始页面结构；Review Agent负责检查页面是否可以进入HTML渲染，重点关注标题复读、页面过空或过满、测验结构不完整、图片引用不合理和动画目标错误；当审核不通过时，Repair Agent根据问题清单尝试返修storyboard；返修后再交给Review Agent复审。审核结果会写入`metadata.agent_review`，便于后续追踪。

图2  Storyboard Agent审核闭环  
Fig.2  Storyboard agent review loop

在实现中，系统没有完全依赖Agent进行底层修复，而是将确定性规则与Agent审核结合起来。例如，当Repair Agent返回非法JSON时，系统不会直接中断非严格模式下的流水线，而是记录`repair_error`并保留当前storyboard；当动画目标或timeline目标与元素ID不一致时，系统使用确定性规则进行修正。这种设计降低了模型输出不稳定对系统运行的影响。

#### 2.4 模板渲染与HTML动画生成

动画生成阶段采用“模板渲染优先，模型兜底”的策略。对于定义、流程、对比、活动、测验和总结等常见教学页面，系统使用模板渲染器将结构化元素转化为稳定HTML。模板中预设了布局、字体、颜色、入场动画和响应式适配规则。对于模板暂不支持或需要更自由视觉表达的页面，系统再调用模型生成HTML片段。该策略兼顾了稳定性与表现力。

生成HTML后，系统会进行布局自检，包括多视口下的文字越界、内容重叠和安全区域检查。当发现部分页面存在越界风险时，系统可通过CSS hotfix进行修复。真实章节测试中，布局自检曾发现第1、4、10页存在小屏越界问题，系统自动进行了CSS修复后继续录制。

#### 2.5 TTS时长驱动的录制同步

音画同步是教学视频生成中的关键问题。系统采用“音频先行”策略：先生成每页旁白音频并测量真实时长，再将`audio_duration_sec`写回storyboard。随后，timing模块根据字幕切分和元素文本相似度，为每个动画元素生成`trigger_at_sec`。HTML中注入`slideDurations`和`slideTimelines`，分别控制页面时长和元素触发时间。

真实测试中曾出现旁白已经进入下一页而画面仍停留在上一页的现象。排查发现，HTML虽然包含真实`slideDurations`，但录制器没有按该数组进行自动翻页，而是退回到“总时长/页数”的均分翻页。由于真实页时长差异较大，均分翻页会造成音画错位。修复后，录制器优先读取`window.slideDurations`，按每页真实音频时长调用`SlideController.next()`，并提前500 ms触发转场，使下一页画面尽量对齐下一段旁白开始。修复后生成的同步版视频时长为261.1 s，与音频总时长一致。

### 3 系统演示与结果分析

#### 3.1 演示章节与运行步骤

系统使用真实教材章节进行演示。演示章节主题为教育数字化转型，最终生成目录为`output\real_chapter_agent_review_test_v6_syncfix`。主要运行步骤包括：

1. 生成或复用真实章节讲稿；
2. 使用`--agent-review`生成并审核storyboard；
3. 生成TTS音频并写入每页真实时长；
4. 渲染HTML动画；
5. 按真实页面时长录制无声视频；
6. 合成音频、字幕和画面，得到最终MP4。

最终命令示例如下：

```powershell
t2v produce input\textbook.docx --from-storyboard output\real_chapter_agent_review_test_v6\lesson13_storyboard.json --output output\real_chapter_agent_review_test_v6_syncfix --theme dark-blue-academic --model ecnu-plus --browser msedge --fps 12 --repair 1
```

#### 3.2 输出结果

系统最终生成的主要产物见表2。

表2  真实章节输出结果  
Table 2  Outputs of the real-chapter experiment

| 产物 | 路径 | 说明 |
|---|---|---|
| MP4视频 | `lesson13.mp4` | 最终有声教学视频 |
| HTML动画 | `lesson13-pipeline-dark-blue-academic.html` | 可浏览器播放的动画页面 |
| 字幕 | `lesson13.srt` | 根据旁白生成的字幕 |
| Storyboard | `lesson13_storyboard.json` | 页面结构与旁白内容 |
| 质量报告 | `lesson13_quality.json` | 自动检查结果 |

该章节最终生成11页画面，包含导入页、概念讲解页、流程页、图示页、反思活动页、知识点检测页和小结页。Agent审核结果为`passed`，审核摘要显示storyboard结构完整，包含导入、核心知识点讲解、互动活动、知识检测及小结。最终MP4成片时长为261.1 s，与音频总时长一致。

#### 3.3 质量检查与问题修复

系统输出质量报告用于记录结构、音频、字幕、布局、图片使用和教学事件覆盖等检查结果。真实章节中，音频、字幕和布局检查均能生成对应报告。质量报告中仍出现`textbook image usage is low: 0/1`警告，原因是本次演示从已有script和storyboard路径重跑，没有完整教材图清单，因此该警告不代表同步或视频生成失败。

在多轮真实测试中，系统暴露并修复了若干问题。第一，Review Agent曾在没有可用教材图清单时要求必须使用`fig8-5`等图片编号，后来通过审核规则明确：只有`metadata.available_images`非空时才强制本地教材图引用；否则允许使用图片描述和结构化图示。第二，Repair Agent偶尔返回非法JSON，系统增加容错，在非严格模式下记录错误并保留当前storyboard。第三，拆页后动画目标和timeline目标可能仍指向旧ID，系统增加了确定性刷新规则，保证动画引用真实存在的元素。第四，录制器曾退回均分翻页，导致音画错位，后续改为按真实`slideDurations`逐页翻页。

#### 3.4 与相关系统的差异

PresentAgent强调从长文档生成带旁白的演示视频，并关注视觉与语音内容的同步[1]。本文系统同样面向文档到视频的自动生成，但更强调教材教学场景中的教学计划、课堂活动、知识点检测和人工/Agent审核流程。SlideTailor关注论文到幻灯片的个性化生成，强调根据用户示例和模板逐步生成可编辑幻灯片[2]。本文系统借鉴了“结构化中间表示”和“可编辑生成”的思想，但输出目标不是静态幻灯片，而是包含配音、字幕和动画的教学视频。

与直接由大语言模型生成完整HTML相比，本文系统更强调确定性控制。常见页面由模板渲染，模型主要承担讲稿、storyboard和少量自由页面生成；页面质量由规则和Agent共同检查；录制阶段由真实TTS时长控制。这种设计降低了模型输出随机性对最终成片的影响，也便于在课程设计中展示系统流程、关键技术和运行结果。

### 4 结束语

设计并实现了一个教材教学视频生成系统，能够从教材内容出发，经过教学计划、讲稿、storyboard、TTS、HTML动画和音视频合成等步骤生成有声教学视频。系统通过教学计划层提升内容组织的教学性，通过结构化storyboard增强中间结果的可检查性，通过多Agent审核与确定性质量增强降低LLM输出不稳定性，通过模板渲染提高动画页面的布局稳定性，并通过真实音频时长驱动录制改善音画同步。真实章节演示表明，系统能够生成包含11页画面、字幕和配音的教学视频，最终成片时长为261.1 s。

后续工作可从三个方面展开：第一，进一步完善教材图片链路，使图片使用率检查能够准确反映真实教材图复用情况；第二，优化页内动画节奏，使元素触发时间更贴近旁白语义且避免过晚出现；第三，开发表单化storyboard编辑界面，使教师能够在不直接修改JSON的情况下调整讲稿、页面元素和检测题。

参考文献：

[1] SHI J W, ZHANG Z Y, WU B, et al. PresentAgent: Multimodal agent for presentation video generation[C]//Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing: System Demonstrations. Stroudsburg: Association for Computational Linguistics, 2025: 760-773.

[2] ZENG W Z, OUYANG M Y, CUI L Y, et al. SlideTailor: Personalized presentation slide generation for scientific papers[EB/OL]. [2026-07-06]. https://arxiv.org/abs/2512.20292.

[3] W3C. WebVTT: The web video text tracks format[EB/OL]. [2026-07-06]. https://www.w3.org/TR/webvtt1/.

[4] Microsoft. Playwright documentation[EB/OL]. [2026-07-06]. https://playwright.dev/.

[5] FFmpeg Developers. FFmpeg documentation[EB/OL]. [2026-07-06]. https://ffmpeg.org/documentation.html.
