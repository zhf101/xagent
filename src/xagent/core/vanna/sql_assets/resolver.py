"""SQL Asset 候选检索。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ....web.models.vanna import (
    VannaSqlAsset,
    VannaSqlAssetStatus,
    VannaSqlAssetVersion,
)


class SqlAssetResolver:
    """按规则检索 SQL Asset 候选。"""

    _token_pattern = re.compile(r"[a-z0-9_]+")

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        question: str,
        kb_id: int | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        normalized_question = str(question or "").strip().lower()
        if not normalized_question:
            return []

        query = self.db.query(VannaSqlAsset).filter(
            VannaSqlAsset.owner_user_id == int(owner_user_id),
            VannaSqlAsset.datasource_id == int(datasource_id),
            VannaSqlAsset.status.in_(
                [
                    VannaSqlAssetStatus.PUBLISHED.value,
                    VannaSqlAssetStatus.DRAFT.value,
                ]
            ),
        )
        if kb_id is not None:
            query = query.filter(VannaSqlAsset.kb_id == int(kb_id))

        assets = query.all()
        scored: list[dict[str, Any]] = []
        for asset in assets:
            score, reason = self._score_asset(asset=asset, question=normalized_question)
            if score <= 0:
                continue
            version = None
            if asset.current_version_id is not None:
                version = self.db.get(VannaSqlAssetVersion, int(asset.current_version_id))
            if version is None:
                version = (
                    self.db.query(VannaSqlAssetVersion)
                    .filter(VannaSqlAssetVersion.asset_id == int(asset.id))
                    .order_by(
                        VannaSqlAssetVersion.is_published.desc(),
                        VannaSqlAssetVersion.version_no.desc(),
                        VannaSqlAssetVersion.id.desc(),
                    )
                    .first()
                )
            scored.append(
                {
                    "asset": asset,
                    "version": version,
                    "score": round(score, 4),
                    "reason": reason,
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[: max(1, int(top_k))]

    def _score_asset(
        self, *, asset: VannaSqlAsset, question: str
    ) -> tuple[float, str]:
        score = 0.0
        reasons: list[str] = []

        asset_code = str(asset.asset_code or "").strip().lower()
        name = str(asset.name or "").strip().lower()
        description = str(asset.description or "").strip().lower()
        intent_summary = str(asset.intent_summary or "").strip().lower()
        keywords = [str(item).strip().lower() for item in asset.match_keywords_json or []]
        examples = [str(item).strip().lower() for item in asset.match_examples_json or []]
        question_tokens = self._tokenize(question)

        if asset_code and asset_code in question:
            score += 1.0
            reasons.append("asset_code_exact")
        if name and name in question:
            score += 0.8
            reasons.append("name_contains")
        if asset_code and asset_code.replace("_", " ") in question:
            score += 0.55
            reasons.append("asset_code_phrase")
        if description and description and any(
            token for token in description.split() if token and token in question
        ):
            score += 0.15
            reasons.append("description_token")
        if intent_summary and any(
            token for token in intent_summary.split() if token and token in question
        ):
            score += 0.2
            reasons.append("intent_token")

        matched_keywords = [item for item in keywords if item and item in question]
        if matched_keywords:
            score += 0.2 * len(matched_keywords)
            reasons.append("keyword_match")

        matched_examples = [item for item in examples if item and (item in question or question in item)]
        if matched_examples:
            score += 0.35 * len(matched_examples)
            reasons.append("example_match")

        name_overlap = self._token_overlap_ratio(question_tokens, self._tokenize(name))
        if name_overlap >= 0.5:
            score += 0.35 * name_overlap
            reasons.append("name_token_overlap")

        keyword_overlap = self._token_overlap_ratio(
            question_tokens,
            {token for item in keywords for token in self._tokenize(item)},
        )
        if keyword_overlap >= 0.5:
            score += 0.25 * keyword_overlap
            reasons.append("keyword_token_overlap")

        intent_overlap = self._token_overlap_ratio(
            question_tokens,
            self._tokenize(intent_summary),
        )
        if intent_overlap >= 0.4:
            score += 0.2 * intent_overlap
            reasons.append("intent_token_overlap")

        return score, ",".join(reasons)

    def _tokenize(self, text: str) -> set[str]:
        return {
            token
            for token in self._token_pattern.findall(str(text or "").lower())
            if len(token) >= 2
        }

    def _token_overlap_ratio(
        self,
        question_tokens: set[str],
        candidate_tokens: set[str],
    ) -> float:
        if not question_tokens or not candidate_tokens:
            return 0.0
        overlap = question_tokens.intersection(candidate_tokens)
        if not overlap:
            return 0.0
        return len(overlap) / len(candidate_tokens)
