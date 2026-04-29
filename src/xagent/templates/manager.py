"""
模板管理器 - 管理模板的扫描与检索
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class TemplateManager:
    """模板系统的核心管理器"""

    def __init__(self, templates_root: Path):
        """
        Args:
            templates_root: Path to the templates directory
        """
        self.templates_root = Path(templates_root)

        # Ensure directory exists
        self.templates_root.mkdir(parents=True, exist_ok=True)

        self._templates_cache: Dict[str, Dict] = {}
        self._initialized = False
        self._init_task: Optional[Any] = None

    async def ensure_initialized(self) -> None:
        """确保初始化完成（惰性加载）"""
        if self._initialized:
            return

        # If there is already an initialization task running, wait for it to complete
        if self._init_task is not None:
            await self._init_task
            return

        # Create and execute the initialization task
        self._init_task = asyncio.create_task(self._do_initialize())
        await self._init_task

    async def _do_initialize(self) -> None:
        """实际初始化逻辑"""
        await self.initialize()
        self._init_task = None

    async def initialize(self) -> None:
        """初始化：扫描所有模板"""
        logger.info("📂 Scanning templates...")
        logger.info(f"  from {self.templates_root}...")
        await self.reload()
        self._initialized = True
        logger.info(f"✓ Loaded {len(self._templates_cache)} templates")

    async def reload(self) -> None:
        """重新加载所有模板"""
        self._templates_cache.clear()

        if not self.templates_root.exists():
            logger.warning(f"Templates directory does not exist: {self.templates_root}")
            return

        logger.debug(f"Scanning directory: {self.templates_root}")
        found_count = 0

        for yaml_file in self.templates_root.glob("*.yaml"):
            try:
                template_info = self._parse_yaml_file(yaml_file)
                template_id = template_info.get("id")
                if not template_id:
                    logger.warning(f"Skipping {yaml_file.name}: missing 'id' field")
                    continue

                self._templates_cache[template_id] = template_info
                logger.info(f"  ✓ Loaded: {template_info['name']}")
                found_count += 1
            except Exception as e:
                logger.error(f"  ✗ Error loading {yaml_file.name}: {e}", exc_info=True)

        logger.info(f"Total templates loaded: {len(self._templates_cache)}")

    def _parse_yaml_file(self, yaml_file: Path) -> Dict[str, Any]:
        """解析单个 YAML 文件"""
        with open(yaml_file, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = yaml.safe_load(f) or {}

        # Validate required fields
        required_fields = ["id", "name", "category", "descriptions"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Validate descriptions contains English
        descriptions = data.get("descriptions", {})
        if not isinstance(descriptions, dict):
            raise ValueError("'descriptions' must be a dictionary")
        if "en" not in descriptions:
            raise ValueError("'descriptions' must contain at least 'en' key")

        # Ensure agent_config exists
        if "agent_config" not in data:
            data["agent_config"] = {}

        # Set default values
        data.setdefault("tags", [])
        data.setdefault("features", [])
        data.setdefault("connections", [])
        data.setdefault("setup_time", "5 min setup")
        data.setdefault("author", "xAgent")
        data.setdefault("version", "1.0")
        data.setdefault("featured", False)

        # agent_config default values
        agent_config = data["agent_config"]
        agent_config.setdefault("instructions", "")
        agent_config.setdefault("skills", [])
        agent_config.setdefault("tool_categories", [])
        agent_config.setdefault("execution_mode", "balanced")

        return data

    def _enrich_template(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """将连接信息合并到 agent_config.tool_categories 中"""
        connections = template.get("connections", [])

        # The agent_config could be an AgentConfig pydantic model or a dict
        agent_config = template.get("agent_config", {})

        if hasattr(agent_config, "model_dump"):
            agent_config_dict = agent_config.model_dump()
        elif hasattr(agent_config, "dict"):
            agent_config_dict = agent_config.dict()
        else:
            agent_config_dict = dict(agent_config)

        tool_categories = agent_config_dict.get("tool_categories", [])
        if not isinstance(tool_categories, list):
            tool_categories = list(tool_categories) if tool_categories else []

        for conn in connections:
            conn_name = conn.get("name") if isinstance(conn, dict) else conn
            if not conn_name:
                continue
            mcp_category = f"mcp:{conn_name}"
            if mcp_category not in tool_categories:
                tool_categories.append(mcp_category)

        agent_config_dict["tool_categories"] = tool_categories

        return {
            "id": template["id"],
            "name": template["name"],
            "category": template.get("category", ""),
            "featured": template.get("featured", False),
            "descriptions": template.get("descriptions", {}),
            "features": template.get("features", []),
            "connections": connections,
            "setup_time": template.get("setup_time", "5 min setup"),
            "tags": template.get("tags", []),
            "author": template.get("author", ""),
            "version": template.get("version", ""),
            "agent_config": agent_config_dict,
        }

    async def list_templates(self) -> List[Dict]:
        """列出所有模板（摘要信息）"""
        await self.ensure_initialized()

        result = []
        for template in self._templates_cache.values():
            result.append(self._enrich_template(template))
        return result

    async def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """获取单个模板（完整信息）"""
        await self.ensure_initialized()
        template = self._templates_cache.get(template_id)
        if template:
            return self._enrich_template(template)
        return None

    def has_templates(self) -> bool:
        """检查是否有可用模板"""
        return len(self._templates_cache) > 0
