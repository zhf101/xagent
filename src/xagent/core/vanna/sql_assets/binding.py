"""SQL Asset 参数装配与校验。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from ....web.models.vanna import VannaSqlAsset, VannaSqlAssetVersion


class SqlAssetBindingService:
    """根据参数契约做显式参数校验与默认值填充。"""

    def bind(
        self,
        *,
        asset: VannaSqlAsset,
        version: VannaSqlAssetVersion,
        question: str,
        explicit_params: dict[str, Any],
        context: dict[str, Any],
        inferred_params: dict[str, Any] | None = None,
        inference_assumptions: list[str] | None = None,
    ) -> dict[str, Any]:
        del asset, question
        explicit_params = dict(explicit_params or {})
        context = dict(context or {})
        inferred_params = dict(inferred_params or {})
        binding_plan: dict[str, Any] = {}
        bound_params: dict[str, Any] = {}
        missing_params: list[str] = []
        assumptions: list[str] = list(inference_assumptions or [])

        for raw_spec in list(version.parameter_schema_json or []):
            spec = dict(raw_spec or {})
            name = str(spec.get("name") or "").strip()
            if not name:
                raise ValueError("parameter_schema_json contains an item without name")

            if name in explicit_params:
                value = explicit_params[name]
                source = "explicit_user"
            elif name in context:
                value = context[name]
                source = "task_context"
            else:
                value = None
                source = None

            if source is None and spec.get("source_policy") == "system_runtime":
                value, source = self._resolve_system_runtime_value(name=name, spec=spec)

            if source is None and name in inferred_params:
                value = inferred_params[name]
                source = "llm_inferred"

            if source is None and "default_value" in spec:
                value = spec.get("default_value")
                source = "default_value"

            if source is None and spec.get("source_policy") == "derived":
                value, source = self._resolve_derived_value(
                    name=name,
                    spec=spec,
                    bound_params=bound_params,
                )
                if source == "derived":
                    assumptions.append(f"{name} was derived from parameter rules")

            required = bool(spec.get("required"))
            if source is None:
                if required:
                    missing_params.append(name)
                    continue
                binding_plan[name] = {"value": None, "source": "omitted_optional"}
                continue

            normalized_value = self._normalize_value(
                name=name,
                value=value,
                data_type=str(spec.get("data_type") or "string"),
            )
            binding_plan[name] = {"value": normalized_value, "source": source}
            bound_params[name] = normalized_value

        return {
            "binding_plan": binding_plan,
            "bound_params": bound_params,
            "missing_params": missing_params,
            "assumptions": assumptions,
        }

    def _resolve_system_runtime_value(
        self, *, name: str, spec: dict[str, Any]
    ) -> tuple[Any, str] | tuple[None, None]:
        kind = str(spec.get("runtime_kind") or name).strip().lower()
        now = datetime.now(UTC).replace(tzinfo=None)
        if kind in {"today", "current_date"}:
            return now.date().isoformat(), "system_runtime"
        if kind in {"now", "current_datetime"}:
            return now.isoformat(), "system_runtime"
        return None, None

    def _resolve_derived_value(
        self,
        *,
        name: str,
        spec: dict[str, Any],
        bound_params: dict[str, Any],
    ) -> tuple[Any, str] | tuple[None, None]:
        derive_from = dict(spec.get("derive_from") or {})
        kind = str(derive_from.get("kind") or "").strip()
        ref = str(derive_from.get("ref") or "").strip()
        if kind == "range_end_exclusive" and ref and ref in bound_params:
            ref_value = bound_params[ref]
            try:
                ref_date = datetime.fromisoformat(str(ref_value)).date()
            except ValueError:
                ref_date = date.fromisoformat(str(ref_value))
            derived = ref_date.toordinal() + 1
            return date.fromordinal(derived).isoformat(), "derived"
        del name
        return None, None

    def _normalize_value(self, *, name: str, value: Any, data_type: str) -> Any:
        normalized_type = data_type.strip().lower()
        if normalized_type == "string":
            return str(value)
        if normalized_type == "int":
            return int(value)
        if normalized_type == "float":
            return float(value)
        if normalized_type == "boolean":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in {"true", "1", "yes"}:
                return True
            if text in {"false", "0", "no"}:
                return False
            raise ValueError(f"Parameter {name} cannot be parsed as boolean")
        if normalized_type in {"date", "datetime"}:
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            text = str(value).strip()
            try:
                datetime.fromisoformat(text)
            except ValueError:
                if normalized_type == "date":
                    date.fromisoformat(text)
                else:
                    raise ValueError(
                        f"Parameter {name} cannot be parsed as {normalized_type}"
                    ) from None
            return text
        if normalized_type == "string_array":
            if isinstance(value, list):
                return [str(item) for item in value]
            return [str(value)]
        raise ValueError(f"Unsupported parameter data_type: {data_type}")
