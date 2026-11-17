# Doc2Present最小论文实验方案（2026-11-08）

状态：PLANNED，供冻结执行方案使用；不是RUNNABLE配置、已完成实验或锁定测试授权。当前代码基准022bc54；本轮只写方案，不连接服务器、不调用模型、不生成媒体。目标是在既有研究计划范围内补论文证据，不继续扩展系统。

## 1. 用人话说要验证什么

只保留两个主问题：①系统判断该不该配图、复用还是检索，是否比简单规则或直接问模型更可靠；②同样一套图和配音，显式语义绑定和事件规划能否减少对象指错、过早、过晚和漏显。事件级成片检查作为共同测量机制，不另开第三条研究主线。

AI生成图、反复修图、通用检索平台和布局美化是P1支撑，不作为主实验跑不起来的理由。正式P0关闭新增生成和自动修复；需要生成时记录generation-candidate/NO_MATCH，不能算获取成功。已生成且来源/权限/语义审核通过的图可预先封入共享候选池，禁止实验中按方法补图。

## 2. 数据和公平性

使用官方Doc2Present固定版本5656f79a4101aa81cb249bbf630dd4e73971a60e的30份PDF，文件hash沿用configs/research/doc2present_inventory_20261104.json。材料包含论文和产品文档，不能统称30份教材章节。参考MP4仅作评价参照，不能给生成链看。

先完成一次文档级曝光清单。已知FineGym、Just Ask、DVC、Factorized、Normalizing Flows、Fast On-the-fly Sparsification至少6份用于过方法开发/诊断，全部进dev，不能当独立测试。其他文档先查现有运行/请求记录；历史不明标unknown，不强称未见。

建议在曝光核对后冻结6 dev/6 validation/18 locked-test：6/6/18是目标，不是现成事实。若发现更多已调试文档，全部归dev，从剩余未用于方法开发的文档中按PDF SHA256升序分validation/test；先分配最多6份validation，其余test。数量在看新结果前固定并如实报告，不为凑数量将dev移回test。若剩余test不足10份，取消“独立正式泛化验证”表述，报告为开发性研究；扩展新来源另议，不自动下载替代样本。

每份文档只取一个短片段，不做整篇长视频。冻结统一的正文识别/抽取规则：去页眉导航后，从正文起首完整段落开始连续取约300–500英文词，保留跨页来源位置和相邻图注；不按模型是否容易配图选择。抽取规则先在dev定稿，locked-test由程序执行，不看模型结果改片段。PDF无法稳定抽取记失败，不换文档。该设计结论限短片段，不称整篇课程效果。

原文、教学目标、讲稿、命题、基础分镜/组件、候选宇宙、主题、音轨、种子、模型别名/可获版本、Prompt与代码commit全部hash冻结。共享内容准备每文档只做一次，最多4次chat（计划/讲稿/分镜/命题图各一次）；每条件不能另写一套讲稿。正式预测不读gold；模型提取的命题不自动成为gold。

RQ1评价全部命题中的前6条knowledge propositions；RQ2取前4条narration propositions（均按来源/旁白span顺序，先固定ID）。不足不补，其他命题照常保留但不进入本次抽样评价，不能删除原文腾位置。不挑正例/容易绑定项，none/拒绑/不确定均保留。命题边界和引用需人工核对，非法来源或边界错误另记上游失败。

RQ1各方法共享源图、冻结外部候选宇宙和NO_MATCH；候选不是完整运行时联网搜索。RQ2各方法共享同一冻结候选子集，不使用各自RQ1挑出的不同图片，否则无法归因绑定/时序差异。源图权利未核实不正式接纳，数据集MIT元数据不替代嵌入图权利；权限不足记录unavailable，不能借此给其他方法新增素材。

## 3. 只跑必要对照

### 实验A：视觉支持与获取决策

主比较6条件：Never Retrieve、Always Retrieve、Keyword Heuristic、Direct LLM、no-source、Proposed。前3个用现有确定性实现，0模型调用；never-retrieve在源图充分时可reuse，不歪曲为永远无图。追加2个既有关键消融：去教学目标、去proposition上下文；不新增router、模型家族或检索系统。没有现成可执行开关的消融先标NOT_IMPLEMENTED，不用换Prompt的临时脚本假装已有实现；冻结前报告缺口，不在test临时补功能。

每文档最多6条×5个模型条件=30次chat，所有条件同一模型/原文可见权限，no-source仅按定义移除源上下文，其他输入长度差异记录。primary指标：人工参考标签上的visual-need macro-F1，以及retrieval-trigger宏F1；分开报告，不把generate当已获取。secondary：每类recall、abstention、有效输出率、候选appropriateness、调用/token/可得费用。无支持样本的类别指标记N/A并报分母，不补造类别或临时平衡。引用合法、schema合法和模型打分不当正确性指标。

### 实验B：对象绑定与动态呈现

绑定主比较：现有lexical/Jaccard、embedding、Direct LLM/VLM、Proposed；现有sentence/element规则作为current基线保留，不另建算法。每文档最多4条×2模型条件=8次chat，embedding批量最多1次请求；规则条件0模型。比较correct/partial/wrong/missing/abstain，主报exact binding accuracy及有效覆盖率；只在非拒绑上报的条件准确率必须同时展示全分母。

时序使用同一音轨和同一冻结视觉对象，复用已有legacy、current semantic、proposition-aware三条件；加proposition-aware without signaling（with signaling为正常proposed），每文档最多4个短片，每条件只录一次。保留无显式binding、sentence替代proposition的既有可执行消融计划：能零新模型从固定预测/时间单元派生则离线评分，不为其新增整套视频或单独模型调用；缺开关则提前标缺，不把不可执行消融写成已跑。

为隔离binding与timing，时序主比较用固定、预先核对的共享对象映射；它是受控时序实验输入，不能写成自动绑定成功，也不能泄漏给绑定预测。另在相同素材上离线用实际预测重算完整对象/时间错误，失败不补正确答案。无对象、拒绑和上游失败在总链报告中保留，不能只评价成功条件。

主指标：wrong-target率及相对人工可接受出现窗口的early/late/missing率；secondary为onset到窗口的距离、signaling目标/密度。只有可判定的真实MP4可见区间才算interval overlap；其余标unobservable，不把runtime当成片区间。细粒度时间不可可靠标注时按原研究计划收缩为onset window，不换指标救结论。

### 共同评价及暂缓项目

使用现有planned→compiled→runtime→rendered四层证据和人工事件标签。主结果不新增LLM裁判调用：已有Judge顺序敏感，不能替代人工参考。若要独立声称event evaluator优于aggregate/Direct VLM，必须另做原计划的评价对照与消融；本最小方案不承担该主张，不将其包装为已证实贡献。

四级整链消融（frozen v1/+visual decision/+binding/+dynamic planning）及重新运行PresentAgent作为原计划“时间允许”项目，暂不进入首批执行预算；原参考视频可描述性展示，输入/配音不同不能据此计算方法增益或公平击败外部系统。学习者实验、额外模型选型和P1生成/修图实验均不做。

## 4. 人工评价：只标必要字段

先在3份dev（建议DVC/FineGym/Normalizing Flows）做30条正式标注pilot：每文档6个视觉决策项目+4个绑定/事件项目，共30项目，两位真实标注者独立、盲方法标签。先核对边界/来源，再标visual need、retrieval need、候选适配、binding、事件类别/可接受窗口；允许uncertain/unobservable。方法输出展示次序打乱，标注不看模型解释或其他标注者答案，分歧另存adjudication。两个AI上下文不是两名人工标注者。

按既有计划：边界agreement目标≥0.80，核心类别κ/α目标≥0.67，并同时报原始一致率/类别分布。达不到时先在dev澄清一次协议，仍不稳定则删除/收缩对应主张，不持续修到过线。正式数据采用相同最小标签，评价gold只进入评价端。人工未到位不阻止服务器环境/开发预跑，但不能把自动Judge结果称正式人工准确率；正式论文结论需等待这一证据。

## 5. 执行顺序与预算

1. 准备：一次曝光清单、数据/候选/音轨manifest和可运行配置；不写新系统。各消融开关、分母和执行入口先核对。旧RUNNABLE仍为lesson_002 development，不直接改名充当Doc2Present正式配置。
2. 服务器单例预跑：仅1份dev，基线+proposed和共享音轨走完整证据链，明确是development smoke；其请求计入后续3文档dev总额，不额外加一套预算。通过环境/来源/ID/音轨/真实录制检查才继续；不要求proposed赢。失败停止，只报告一个可定位阻塞，不开始新架构或换样例。
3. dev标注pilot及3份dev结构化预跑；随后6份validation固定一次选择阈值/方法，记录后冻结，不循环调参。locked-test清单、协议和人工授权齐全后，仅运行一次正式test，不因效果不佳重发或换样。
4. 汇总：按文档配对统计、保留失败分母，生成论文表格/代表性成功与失败案例；未通过贡献gate的主张删除。

硬请求上限按每文档43次计：公共内容4 chat+RQ1 30 chat+binding8 chat+embedding1。3 dev最多129，目标6 validation最多258、18 test最多774，总计最多1161次传输；另服务器健康检查最多1次，总上限1162。是计划上限，不是必花预算，不执行的阶段/条件不补发；任何公共准备额外批次必须占本阶段余额，不能称底层调用不计数。若曝光清单改变各split数量，在预测前重新计算预算manifest，不能增加30文档范围。

TTS每文档最多一次句级生成批次、保存实际WAV/句界供所有条件共用。4视频/文档上限，3 dev+24正式/验证目标最多108个短片（smoke计入dev）；单片≤180秒作为录制资源上限，超限前停该case、原始音轨保留，不裁删内容凑长度。无图片API、额外模型裁判、自动生成修复或自动任务重试。

tokens以服务端usage累计；账本到300万实测tokens后停止发出下一请求，这是软停线（最后一个请求可能越线，明确记录），不是可精确保证的硬token额度。费用只有服务端usage/可核验账单才记实测；缺失记未知，不将价格表估算冒充费用。阶段串行放行，开发API并发≤2，逐请求先预留名额再发送，底层重试=0。以上为拟议执行预算，不代表本次已授权/启动收费批量。

API整体不可用、凭据/配额错误、来源hash/权限/泄漏或公共渲染基础设施错误立即停整个阶段；内容预测/绑定/单页布局失败记录为该case失败并继续其他预定独立case，不修样例或扩大调用。严格验收失败不得标增强成功，development回退如发生单列fallback，不进入增强成功数，也不从统计分母删去。更强模型/临时手填关系/人工修图不得混入正式条件。

## 6. 服务器与可复现性

精确commit已推送，服务器仅拉取该commit，先source /ai/data/use_ai_env.sh。代码/数据分开，运行资产放/ai/data/textbook-to-video；每任务新run_id，旧失败不可覆盖。使用既有preflight：development smoke先检查rendering/LLM；pilot/validation/locked-test须Git已跟踪ConfigPath、clean/pushed和全部hash/权限/输出检查。正式锁定测试还须既有locked_test_authorization，本文不代签。

Windows SAPI不能直接放Linux运行。最省事方案是本机统一生成一次英文句级WAV/句界，连同旁白/hash/声音参数整体上传并在服务器只复用；所有方法同字节音轨，配音映射不明即停。如果选服务器后端，必须在dev预跑前明确且所有条件共用，不能中途换音色/引擎。浏览器、字体、ffmpeg/ffprobe、模型ID/版本可获信息和依赖版本写快照，不能假定本机状态等于服务器。

## 7. 统计、结论和论文交付

每份文档先算各条件指标，再作配对文档级差值/95% bootstrap区间，不把多个命题/事件当独立文档；小样本区间如不稳定如实展示。RQ1共同主要结果固定为visual-need macro-F1和retrieval-trigger宏F1，分别报告；RQ2主要结果固定为exact binding accuracy（同时报有效覆盖率）、wrong-target及early/late/missing率。主要比较预定Proposed对Direct（决策/绑定）以及对current semantic（时序），其余条件帮助解释机制；其他指标作次要解释，不能事后挑显著项。类不平衡、文档类型差异、素材不可用、unobservable和失败率单独报告。

未优于Direct/规则时，不换数据或追加模型救分；删除方法优势主张。无source/目标/context消融无稳定差异就删除对应机制主张。timing不优于current semantic则只保留binding或失败分析。没有学习者实验不写提高学习效果。生成/布局工程视频只作系统案例，不混作正式方法证据。

只交付：冻结配置/输入manifest/曝光split清单；逐条原始预测和调用账本；共用音轨/候选hash；planned/runtime/最终抽帧和人工记录；RQ1/RQ2主表、失败/成本表、必要消融；一份短结论边界。实现与实验设计章节现在即可写，正式结果/摘要结论等锁定批次和人工评价后写。工期取决于人工评价到位和预跑结果，不承诺某日完成，不为收尾继续加功能。
