根据教材联合规划教学页面、独立讲解动作、旁白和关注目标。只使用 source_units 中的事实；lesson_plan 是教学组织参考，不能代替原文证据。覆盖本块教材的教学内容，按空间和讲解需要分为多个完整页面。不要清空信息来适配一页。每页旁白自然、简洁，通常30–60秒，不必凑长度。

动作单位是一个可独立说明的对象、操作或关系。每个动作包含当前 focus、必要 relation_refs 和仅作为上下文的 background。必要关系的全部端点不等于每次都要全部高亮。只在解释联合关系确需时联合 focus。无须强调时可给空 focus。所有页面内容在讲解中保持可见。

保留条件、分支、对比、依赖与并列关系，不将并列输出或不同条件状态画成线性流程。不要添加人数、阈值、因果、操作次序或来源未给出的结论。每个 visual_relation 和 teaching_action 都必须用 source_refs 引用一到多个 source_units.id；只返回输入中存在的编号，不要逐字抄写 source_units.text，也不要输出 source_quote。编号只用于定位来源，不代表关系已被独立证明；不得仅凭 lesson_plan 添加来源未支持的事实。不能把多个相关陈述合成更强保证。visual_relations 必须说明现有组件实际如何表达关系，不能依赖没有生成的箭头。

使用现有组件，不写 HTML/SVG。支持 heading/text（text）、flow_step/activity_step（steps字符串数组）、comparison_panel（items数组，每项title/content）、table（headers字符串数组、rows二维字符串数组）、image（只允许引用 available_images 中 source_image_id，不编造文件路径）。已有教材图片合适时可以复用；定义、对比或表格已足够时不强制补图。flow_step 表示有依据的先后步骤，comparison_panel 会显示对比样式。不要把关系不明的不同对象塞进同一个文本块后假装可分别高亮。

每个元素给唯一的安全 id（字母数字、下划线、短横线）。关注引用为 {"element_id":"该页id","index":0}；index 是 steps/items/rows 的0起始位置，null 表示整个元素。不要引用装饰节点或不存在的对象。不安排秒数，程序使用实测音频 cue 决定每个动作的持续时间。

只返回 JSON：
{"segments":[{"visual_type":"illustration","elements":[{"id":"title","type":"heading","text":"标题"}],"visual_relations":[{"id":"关系id","kind":"语义关系","from":[{"element_id":"元素id","index":null}],"to":[{"element_id":"元素id","index":0}],"source_refs":["raw-unit-0001"],"display_explanation":"组件如何真实表达关系"}],"teaching_actions":[{"teaching_goal":"独立讲解目标","source_refs":["raw-unit-0001"],"narration":"该动作旁白","focus":[{"element_id":"元素id","index":0}],"focus_reason":"为什么需要强调；不需要时说明理由","relation_refs":["关系id"],"background":[{"element_id":"元素id","index":null}]}]}]}

动作和页面结构由你决定；id、引用、旁白必须相互一致。不要返回 narration 总文本或事件时间，程序会按动作顺序确定性派生。
