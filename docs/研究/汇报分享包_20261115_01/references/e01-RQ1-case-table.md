| 命题 ID 尾号 | 真实命题 | ordinary 原决策 | Never | Always | Direct | Proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 003 | 它通过一系列可逆变换，把复杂的数据分布"压平"成一个简单的高斯分布。 | generate | none | retrieve | generate | generate |
| 005 | 标准化流最常用的结构叫分裂耦合流，简称SCF。它的做法很巧妙：把维度分成两半，只对其中一半做变换，另一半原封不动。 | none | none | retrieve | generate | generate |
| 008 | 每个像素都依赖前面所有像素。 | generate | none | retrieve | generate | none |
| 010 | 每个通道的条件分布是高斯，均值和方差由Conv-LSTM来预测。 | generate | none | retrieve | generate | generate |
| 012 | 多尺度流在每一层通过SQUEEZE把空间分辨率减半、通道数翻倍，然后SPLIT把特征分成两部分。 | none | none | retrieve | generate | none |
| 013 | 这就是"只在先验上自回归"带来的效率红利。 | none | none | retrieve | none | generate |
| 014 | 在CIFAR-10上，mAR-SCF的bits/dim达到3.24，优于Glow的3.35和Flow++的3.29。 | none | none | retrieve | none | none |
| 016 | mAR-SCF的核心贡献是：用多尺度自回归先验弥补了分裂耦合流的表达力短板， | none | none | retrieve | generate | none |
| 019 | 课堂练习：给定一个多尺度流模型的结构，画出其潜在空间分解示意图，并标出mAR先验应用的位置。； | generate | none | retrieve | generate | none |
| 021 | 请完成这几个知识点检测题：标准化流模型通过什么方式实现精确似然计算？； | none | none | retrieve | none | none |

逐项 A/B 标签、来源编号、原始预测与轴评价见 cases.json；方法身份和匿名映射见 groups/。
