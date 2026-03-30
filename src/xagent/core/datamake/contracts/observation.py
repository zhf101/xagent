"""
`Observation Contracts`（观察结果契约）模块。

这一层定义所有下游通道回流给主脑时应遵守的统一结构。
无论结果来自用户回复、审批结论还是执行结果，最终都应该汇聚到
统一的 observation 语言。
"""


class ObservationEnvelopeContract:
    """
    `ObservationEnvelopeContract`（观察结果外壳契约）占位类。

    所属分层：
    - 代码分层：`contracts`
    - 需求分层：`Observation`（观察结果）回流统一契约
    - 在你的设计里：各通道回流到主脑前的统一包裹层

    主要职责：
    - 统一所有 `interaction`（用户交互）、
      `execution`（执行）、`supervision`（人工监督）结果的回流结构。
    - 让主脑只处理一种回流壳，而不用为每条通道写分裂逻辑。
    """


class PauseObservationContract:
    """
    `PauseObservationContract`（等待态观察结果契约）占位类。

    主要职责：
    - 表达“当前流程进入等待态”的标准化 observation。
    - 用于用户待回复、审批待处理、异步执行待恢复等暂停场景。
    """
