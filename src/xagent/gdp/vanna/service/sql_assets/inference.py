"""SQL Asset 参数智能推断服务。

这个模块把 LLM 的职责限制在“猜参数”，而不是“改 SQL”。
这样可以把运行时不确定性压缩到 bindings 层，避免模型越权篡改资产模板。
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable

from xagent.gdp.vanna.model.vanna import VannaSqlAsset, VannaSqlAssetVersion
from xagent.web.services.model_service import get_default_model


class SqlAssetInferenceService:
    """让 LLM 只做参数识别，不负责改写 SQL。"""

    def __init__(
        self,
        *,
        llm_callable: Callable[..., Any] | None = None,
        llm_resolver: Callable[[int | None], Any] | None = None,
    ) -> None:
        self.llm_callable = llm_callable
        self.llm_resolver = llm_resolver or get_default_model

    async def infer_bindings(
        self,
        *,
        asset: VannaSqlAsset,
        version: VannaSqlAssetVersion,
        owner_user_id: int,
        question: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """根据问题和上下文推断参数绑定。

        返回结构会被后续 `SqlAssetBindingService` 二次校验，因此这里允许模型给出
        候选值，但不直接视为可信最终值。
        """
        parameter_schema = list(version.parameter_schema_json or [])
        if not parameter_schema:
            return {
                "asset_code": str(asset.asset_code),
                "bindings": {},
                "missing_params": [],
                "assumptions": [],
                "model_name": None,
            }

        prompt_bundle = self._build_prompt(
            asset=asset,
            version=version,
            question=question,
            context=context,
        )

        if self.llm_callable is not None:
            raw = await self._call_maybe_async(
                self.llm_callable,
                messages=prompt_bundle["messages"],
                system_prompt=prompt_bundle["system_prompt"],
                user_prompt=prompt_bundle["user_prompt"],
                asset=asset,
                version=version,
                question=question,
                context=context,
            )
            parsed = self._parse_inference_result(raw, parameter_schema=parameter_schema)
            parsed["model_name"] = None
            return parsed

        llm = self.llm_resolver(int(owner_user_id)) if self.llm_resolver else None
        if llm is None:
            raise ValueError("No default chat model is configured for SQL asset binding")

        raw = await llm.chat(
            prompt_bundle["messages"],
            response_format={"type": "json_object"},
        )
        parsed = self._parse_inference_result(raw, parameter_schema=parameter_schema)
        parsed["model_name"] = getattr(llm, "model_name", None)
        return parsed

    def _build_prompt(
        self,
        *,
        asset: VannaSqlAsset,
        version: VannaSqlAssetVersion,
        question: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """构造专门给参数推理使用的 Prompt。"""

        system_prompt = (
            "You bind parameters for a reusable SQL asset. "
            "Do not write, rewrite, or explain SQL. "
            "Return only one JSON object with keys: asset_code, bindings, missing_params, assumptions. "
            "Use only parameter names from the provided schema. "
            "Only infer values that are clearly supported by the question or context. "
            "If a required parameter cannot be determined, put its name in missing_params. "
            "assumptions must be a short list of inference assumptions."
        )
        user_payload = {
            "asset": {
                "asset_code": str(asset.asset_code),
                "name": str(asset.name),
                "description": asset.description,
                "intent_summary": asset.intent_summary,
                "match_keywords": list(asset.match_keywords_json or []),
                "match_examples": list(asset.match_examples_json or []),
            },
            "version": {
                "version_id": int(version.id),
                "template_sql": str(version.template_sql),
                "parameter_schema_json": list(version.parameter_schema_json or []),
            },
            "question": str(question or "").strip(),
            "context": dict(context or {}),
        }
        user_prompt = (
            "Infer parameter bindings for the current SQL asset.\n"
            + json.dumps(user_payload, ensure_ascii=False, indent=2)
        )
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    async def _call_maybe_async(self, func: Callable[..., Any], /, **kwargs: Any) -> Any:
        """兼容同步/异步注入，便于测试或自定义模型接入。"""

        result = func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _parse_inference_result(
        self,
        raw: Any,
        *,
        parameter_schema: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """解析模型返回，并收敛到绑定契约。"""

        if isinstance(raw, dict) and "bindings" in raw:
            return self._normalize_payload(raw, parameter_schema=parameter_schema)

        if isinstance(raw, dict) and "content" in raw:
            raw = raw.get("content")

        content = self._strip_or_none(raw)
        if content is None:
            raise ValueError("LLM returned empty SQL asset binding response")

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match is None:
            raise ValueError("Failed to parse SQL asset binding JSON from LLM response")

        try:
            payload = json.loads(json_match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError("Failed to decode SQL asset binding JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("SQL asset binding response must be a JSON object")
        return self._normalize_payload(payload, parameter_schema=parameter_schema)

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        *,
        parameter_schema: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """过滤掉 schema 之外的参数名，防止模型越权输出无关字段。"""

        allowed_names = {
            str(item.get("name") or "").strip()
            for item in list(parameter_schema or [])
            if str(item.get("name") or "").strip()
        }
        bindings_raw = payload.get("bindings") or {}
        if not isinstance(bindings_raw, dict):
            bindings_raw = {}
        filtered_bindings = {
            str(name): value
            for name, value in bindings_raw.items()
            if str(name) in allowed_names
        }

        missing_params = [
            str(name).strip()
            for name in list(payload.get("missing_params") or [])
            if str(name).strip() in allowed_names
        ]
        assumptions = [
            str(item).strip()
            for item in list(payload.get("assumptions") or [])
            if str(item).strip()
        ]
        return {
            "asset_code": self._strip_or_none(payload.get("asset_code")),
            "bindings": filtered_bindings,
            "missing_params": missing_params,
            "assumptions": assumptions,
        }

    def _strip_or_none(self, value: Any) -> str | None:
        """统一字符串清洗，空串按 `None` 处理。"""

        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

