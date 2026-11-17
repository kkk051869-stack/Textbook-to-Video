# RQ2 Proposed v1.1小规模公平对比（2026-11-10）

**结论：未观察到Proposed的实际方法优势。** 新来源6个命题上，Proposed的6份响应均被其自身结构/引用契约拒绝；Direct多对象输出6份结构有效，但有不完整或不充分的关系选择；Lexical返回4个对象、2次拒绑。本轮主要暴露的是Proposed输出契约的有效覆盖与成本问题，不能将6次无效等同于6次语义选错，也不能将Direct结构通过等同于正确率。

## 条件、样本与公平性

基线HEAD为14f3113，加上未提交的v1.1代码；实际Proposed核心SHA256仍为 `18e7df86d12364527c8af3fbe3aaaf0e504f98080921836dcb1ccf8222ea0677`，与两例真实验证的冻结快照一致。没有修改Proposed或Lexical。按用户对输出接口冲突的明确答复，只在本地实验适配器中将Direct的“at most one”及单ID输出改为零/单/多ID集合，保留其语义规则、来源和候选，不使用Proposed的角色推理替代Direct。原Prompt、输出适配后的Prompt及代码都保留。旧Direct单目标结果不冒充新版本公平比较结果。

共8项：6项新来源配对比较，另2项已曝光ri/SPLIT仅作历史回顾。预算12次刚好覆盖6项×2模型方法，因而没有为凑8项新比较重复付费；两项开发回顾不计入本轮公平比较结论。

新增来源为Doc2Present固定版本的《Self-Supervised Monocular Scene Flow Estimation》（S1–S3，PDF页3–4、完整Figure3）和《Optimizing Rank-based Metrics with Blackbox Differentiation》（R1–R3，PDF页3–4、完整Algorithm1）。原件在主工作树 `.local/data/external/doc2present/`，复制件hash与库存清单一致。当前分支配置、文档及可访问运行记录中未发现两文档用于方法调整；库存曝光仍是HISTORY_AUDIT_PENDING，不能认证跨机器完整历史，故为新增来源探索性结果，不称独立locked/test或泛化实验。TinyAgent在调用前检查发现本地PDF缺原生文本，未纳入，未用不明OCR补来源。

每篇固定6个源图候选，包含完整关系区域及原图局部；不因输出改变候选。三者获得相同命题、完整来源上下文及候选文字，两个模型还获得相同完整图与全部候选像素。Lexical固有地只使用文字并选单个最大匹配，不给它人工关系推断；不因其能力边界简单便宣称复杂方法有效。

事前 `teaching_requirements.json` 固定目标、合理关注区域与关系要求，允许多解。模型不读取这些判据。命题逐字来自PDF抽取文字，保留raw与空白折叠派生记录；跨行连字符未补写。执行者已看过研究历史与源图，本轮评价是来源核对，不是独立盲标或人工Gold。未调用Judge，不计算准确率。

共同配置：ecnu-plus，temperature=0，max_tokens=4096，timeout=120秒，重试0；按命题交替P/D、D/P顺序。Direct只适配输出数量和解析，Proposed的额外引用证明是其方法成本。共同比较的是关注集合合理性，而非要求Direct凭空具有Proposed的内部证明字段；Direct原契约不保证逐字引用，不能拿其“无引用拒绝”当作来源证明更可靠。

## 逐项实际结果及来源判断

P=Proposed v1.1；D=Direct集合输出适配版；L=原Lexical。图/算法整体也是合法候选，不按返回ID数量奖励。以下P“无有效集合”严格保留程序结果；原始拟支持对象只用于失败诊断，不恢复为成功。

|项目与事前教学要求|P实际结果|D实际选择|L实际选择|来源能够判断的差异与不确定性|
|---|---|---|---|---|
|S1 scene-decoder-outputs：联合decoder输出残差scene flow和非残差disparity，需保留解码器→两输出关系|INVALID_RESPONSE，无有效集合；source quote不连续匹配|scene-decoder、scene-outputs、scene-figure|scene-outputs|D有完整图，关系可覆盖，但三者重叠冗余；L定位两个输出，缺decoder上下文，属部分关系覆盖。P原拟支持与D同一集合，不能据此称P提供额外对象推断|
|S2 scene-flow-warping：optical flow用于warp feature map，关注操作及输入路径|INVALID_RESPONSE；attention_role填action（不在枚举）|scene-warping|scene-warping|D/L对象选择相同且合理，但单裁片没有完整flow来源和feature-map路径，只能判局部定位/部分覆盖。P原拟支持projection、warping、完整图可能覆盖更多上下文，但并未形成有效绑定，不能计方法优势|
|S3 scene-loss-components：总损失由disparity和scene-flow两项加权；当前架构候选不含损失节点/公式，拒绑有依据|INVALID_RESPONSE；focus_quote不在提交的source_quotes内|scene-outputs、scene-figure|scene-decoder|这些是预测输出及生成它们的模块，不是损失加权关系，图中没有λ或两损失合成；可作背景关注，未满足本句关系要求。D解释“which quantities are being minimized”还存在把预测量与损失混同的风险。P原回答也把输出与损失关联，不能说其门禁已识别并纠正了此语义问题|
|R1 rank-gradient-algorithm：定位Algorithm1中的梯度计算过程|INVALID_RESPONSE；candidate_label_quote未逐字匹配|rank-algorithm|rank-backward|D完整算法与L后向过程都有原文/代码支持，L也覆盖核心梯度过程；没有P独有的问题被解决|
|R2 rank-pronoun-implication：“This implies”承接只需黑盒forward即可算backward，因此可复用优化solver|INVALID_RESPONSE；source quote未定位|rank-definition|拒绑（score=0）|D对黑盒Ranker指代有依据，但单定义行未显示如何用于backward，关系仍部分；原算法有可用说明，L词面阈值造成覆盖遗漏。P原拟支持定义、backward及整体算法，但引用失效，不能转换为有效覆盖|
|R3 rank-forward-for-backward：forward黑盒实现与backward计算之间的依赖|INVALID_RESPONSE；action_quote未在提交引文定位|rank-definition、rank-forward、rank-backward、rank-algorithm|拒绑（score=0）|D选择包含完整算法，原图可核对同一Ranker在前后向中调用，支持关系，但集合有冗余。L遗漏来源中可解释的过程；P原拟支持集合与D一致，没有独有推断增益|
|开发回顾L1 flows-complex-s1：ri继续变换、li不变|复用上轮v1.1 BOUND ri（patient）|历史单目标Direct：ri；不是本轮集合适配版|历史Lexical：ri|有来源支持，修正了actor-only任务偏差；与简单方法选同一对象，不能当独立优势证据|
|开发回顾L2 flows-complex-s2：SPLIT固定li，另一分支继续变换|复用上轮v1.1 BOUND_MULTIPLE：SPLIT、ri|历史单目标Direct：SPLIT；不是同输出范围比较|历史Lexical：SPLIT|联合选择有上下文依据但li候选缺失；不因P可多选就写它优于旧单目标Direct，完全排除于新公平结论|

新6项中没有三方有效集合完全一致的项目；D/L仅S2完全同选，S1存在集合包含关系，R1均覆盖梯度过程但粒度不同。这个描述不构成胜率。原回复细节和新结果均保存，未改旧预测/判词。

## Proposed失败位置：原回复与程序拒绝分开

|项目|实际首个拒绝点|离线核对发现的具体问题|
|---|---|---|
|S1|源文引文|输出区域的SUPPORTED行写“disparity and scene flow together”和“disparity and scene 1Even though... flow together”；输入抽取中有脚注跨列插入，模型拼接/加省略号，不能逐字锚定。不是证明对象选错|
|S2|全局Schema|projection与warping角色写action，契约只允许actor/patient/input/output/relation/null；没有静默映射为relation|
|S3|关注引文|scene-outputs的focus_quote为损失短语，但其提交source_quotes只谈decoder输出；另有完整图候选标签“Figure 3. Our …”与提供标签“Figure 3: …”不匹配|
|R1|候选标签|模型引用“function BACKWARDPASS”，提供的候选文字以“BACKWARDPASS:”开头；图像/原伪代码里确有function字样，但未符合候选文字字段契约|
|R2|源文引文|输入保留“Algo- rithm”“black- box”等PDF跨行抽取形式；模型引用常规拼写Algorithm/blackbox，现有定位器不将这种连字符差异视为等价|
|R3|动作引文|rank-forward的action_quote填required，但该行引用的是算法forward代码，不含该词；另有backward函数签名与工程候选标签形式不一致|

这些是本次固定输入预处理和冻结方法契约共同作用的失败，尤其排版差异不能计为语义错误。来源对两方法相同，但逐字引用风险是Proposed额外承担的机制代价。本轮没有根据结果修原文、标签、解析器或Prompt，也未用离线解析诊断把INVALID改成成功；仅保留差异以免把失败误归因于模型知识理解。

## 有效覆盖和成本

以下是工程计数，不是教学准确率。Proposed：0/6份方法输出通过、6/6 INVALID、0次有效拒绑、0份部分证据输出；Direct：6/6结构有效（3单对象、3联合集合），0拒绑，但不能全部判语义充分；Lexical：4/6绑定、2/6拒绑，0模型请求。Direct引用真实性未按Proposed内部契约保证；本报告用相同来源和预先关系要求审阅其选择。

|方法|本轮请求|输入tokens|输出tokens|总tokens|请求耗时合计|费用|
|---|---:|---:|---:|---:|---:|---|
|Proposed|6|43692|7685|51377|310.576秒|未返回|
|Direct集合适配|6|30888|1239|32127|56.937秒|未返回|
|Lexical|0|0|0|0|未单独计时|无模型费用|
|合计|12|74580|8924|83504|367.513秒|未知，不估算|

12次传输均OK，不等于12份方法输出有效；Proposed token量约为Direct的1.60倍，请求耗时合计约5.45倍。不能从该代理服务耗时外推部署速度。两项开发结果直接复用，旧调用用量不混入本轮。

## 判断与证据入口

本批没有观察到Proposed解决Direct未解决的问题。Direct相对Lexical在R2/R3取得有来源支持的关注对象，但仍有S3关系不足等问题，不能因此宣称Direct是语义真值。Proposed原始候选支持判断常与Direct一致或提供更广上下文，当前却未能形成可用输出，不能用这些意向替代结果。

“未观察到优势”限于当前冻结方法在这6个新来源命题上的实际可用价值；纯语义推断能力谁更好仍证据不足。不能据此判论文总体无价值，也不能将两个开发案例通过推广为方法已稳定。当前不支持扩大实验或优势主张；本轮按要求收口，不修复、不追加请求。

完整目录为本工作树 `.local/rq2-v11-fair-20261110-01/`：

- `teaching_requirements.json`、`selection.json`、`inputs/`：事前来源判据、选择/曝光依据、原PDF与raw/派生文本、候选图；原图与所有裁片已实际查看。
- `prepared_prompts/`：Direct原Prompt、授权输出适配后的Prompt和未改的Proposed Prompt；`code_snapshot/`：本轮实际代码及本地驱动。
- `protocol.json` SHA256：`da224d162d12beb4122c3b06300c23c86f3e64daaa90f18aadd9a38d18b8aa60`；执行前后输入和方法hash核对通过。
- `run-01/calls.json`、`prompts/`、`results/`：12份原始请求/回复和实际结果；`analysis.json`：字段失败诊断和分方法成本；`development-reuse.json`：两条开发回顾的原文件hash与不公平可比标记；`usage.json`、`integrity.json`：成本和完整性结果。

development预检通过（33项检查测试通过），输出适配离线检查通过；未跑全量测试，未重复上轮83项绑定测试。模型总请求严格12次，无重试、无Judge、无新Embedding、无图片生成/TTS/录制。生产代码及三方法核心逻辑本轮未改，只有授权的Direct输出适配；无关修改保留，未提交/推送，未更新腾讯文档。