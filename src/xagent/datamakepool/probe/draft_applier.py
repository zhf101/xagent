"""Probe draft applier。"""

from __future__ import annotations

from xagent.datamakepool.conversation.flow_draft_service import FlowDraftService

from .finding_normalizer import NormalizedProbeFeedback


class FlowDraftProbeDraftApplier:
    """把 probe 归一化结果写回 FlowDraft。"""

    def __init__(self, flow_draft_service: FlowDraftService):
        self._flow_draft_service = flow_draft_service

    def apply(
        self,
        *,
        draft_id: int | None,
        feedback: NormalizedProbeFeedback,
    ) -> None:
        if draft_id is None:
            return
        self._flow_draft_service.apply_probe_findings(
            draft_id,
            findings=list(feedback.findings or []),
            param_updates=list(feedback.param_updates or []),
            mapping_updates=list(feedback.mapping_updates or []),
            step_updates=list(feedback.step_updates or []),
        )
