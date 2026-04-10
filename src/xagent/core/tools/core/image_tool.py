"""
Image generation tool for xagent

This module provides image generation capabilities using pre-configured image models
passed from the web layer.
"""

import base64
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import parse

import aiohttp

from ...model.image.base import BaseImageModel
from ...workspace import TaskWorkspace

logger = logging.getLogger(__name__)


class ImageGenerationToolCore:
    """
    Image generation tool that uses pre-configured image models.
    """

    # Enhanced description for generate_image tool
    GENERATE_IMAGE_DESCRIPTION = """
根据文本 prompt 生成高质量图片。

当收到用户请求时，请先把原始需求重写并补充为**专业的 image generation prompt**：
- 增加**视觉细节**，例如风格、构图、光线、色彩、材质、氛围
- 把抽象概念转成**具体可视化场景**
- 文本处理优先级：
  1. **Direct text display**：用户明确指定的文本、姓名、日期、数字、引语，必须直接以可读文字形式出现在图中
  2. **Visual description**：品牌名、抽象概念、风格词，优先转成视觉元素表达
  3. **Mixed approach**：如果用户同时给了明确文本和风格要求，就同时保留精确文本与视觉表达

- 对于贺卡、海报、banner 等以文字为主的设计，必须保留用户指定文字，并让其可读
- 尽量使用生动、具体的关键词（逗号分隔）提升效果
- 始终生成 **positive prompt**（想要的内容）和 **negative prompt**（要避免的内容，如低质量、模糊、文字伪影、文字变形、拼写错误、假 logo、品牌 logo、商标符号）
- 涉及品牌/logo 时，优先写成视觉描述，例如 “tech company logo”，不要直接写具体品牌名
- 对一般概念，也要写成可视化表达，例如 “2M downloads text” 或 “million counter”

可用模型（⭐[DEFAULT] 表示当前配置的默认模型）：
{}

**重要：优先使用标记为 ⭐[DEFAULT] 的默认模型。只有当用户明确要求其他模型时，才填写 model_id。**

参数：
- prompt（必填）：带有视觉细节的优化后图片描述
- size（可选）：图片分辨率，格式为 "width*height"，例如 "1024*1024"、"1280*720"、"1920*1080"
- width（可选）：目标宽度（像素），通常与 height 配合使用
- height（可选）：目标高度（像素），通常与 width 配合使用
- resolution（可选）：分辨率，格式为 "WIDTHxHEIGHT"，例如 "1920x1080"
- aspect_ratio（可选）：宽高比，例如 "1:1"、"3:2"、"16:9"、"21:9"；会覆盖由 size 推导出的比例
- negative_prompt（可选）：不希望出现的元素；为空时可自动生成
- model_id（可选）：指定模型名；留空则使用 ⭐[DEFAULT]

**图片尺寸说明：**
- 不同模型支持的尺寸能力和约束不同
- **Gemini models**：使用 aspect ratio + 尺寸桶（1K/2K/4K）体系。精确像素会被映射到最接近的受支持比例和尺寸桶，最终输出尺寸可能与请求值略有差异
- **OpenAI models**：只支持若干预设尺寸，例如 256x256、512x512、1024x1024
- **DashScope models**：支持的尺寸选项较少
- **Xinference models**：基于 Stable Diffusion，通常支持更灵活的尺寸

尺寸参数优先级（从高到低）：
1. aspect_ratio + size（aspect_ratio 决定比例，size 决定分辨率桶）
2. width + height（目标尺寸，会近似到模型支持的最接近值）
3. resolution（另一种尺寸写法）
4. size（简写格式）

生成后的图片会自动保存到 workspace。
    """.strip()

    # Description for edit_image tool
    EDIT_IMAGE_DESCRIPTION = """
使用文本 prompt 编辑现有图片。

这个工具允许你通过描述想要的改动来修改已有图片。模型会理解这些要求，并把改动应用到图片上。

常见用法：
- 修改图片中的物体、人物或场景
- 调整颜色、光线或整体风格
- 添加或移除元素
- 修复瑕疵或增强清晰度
- 转换图片风格（例如改成油画、卡通等）
- 调整尺寸或画幅

涉及图片中文字时：
- **Text modifications**：如果要修改图片里已有文字，请明确说明要改哪段文字、改成什么
- **New text addition**：如果要新增文字，请明确写出具体文本和位置，例如 “在顶部加入 Happy Birthday 文本”
- **Text removal**：如果要删除文字，请明确指出要删除哪些文字元素

可用模型（⭐[DEFAULT] 表示当前配置的默认模型）：
{}

**重要：优先使用标记为 ⭐[DEFAULT] 的默认模型。只有当用户明确要求其他模型时，才填写 model_id。**

参数：
- image_url（必填）：单张图片路径/URL/file_id（同时支持 `file_id` 和 `file:file_id`），或用于多图编辑的路径/URL/file_id 列表
- prompt（必填）：描述希望进行的编辑和改动
- negative_prompt（可选）：结果中不希望出现的元素
- size（可选）：图片分辨率，格式为 "width*height"，例如 "1024*1024"、"1280*720"、"1920*1080"
- width（可选）：目标宽度（像素），通常与 height 配合使用
- height（可选）：目标高度（像素），通常与 width 配合使用
- resolution（可选）：分辨率，格式为 "WIDTHxHEIGHT"，例如 "1920x1080"
- aspect_ratio（可选）：宽高比，例如 "1:1"、"3:2"、"16:9"、"21:9"；会覆盖由 size 推导出的比例
- model_id（可选）：指定模型名；留空则使用 ⭐[DEFAULT]

**图片尺寸说明：**
- 不同模型支持的尺寸能力和约束不同
- **Gemini models**：使用 aspect ratio + 尺寸桶（1K/2K/4K）体系。精确像素会被映射到最接近的受支持比例和尺寸桶，最终输出尺寸可能与请求值略有差异
- **OpenAI models**：只支持若干预设尺寸，例如 256x256、512x512、1024x1024
- **DashScope models**：支持的尺寸选项较少
- **Xinference models**：基于 Stable Diffusion，通常支持更灵活的尺寸

尺寸参数优先级（从高到低）：
1. aspect_ratio + size（aspect_ratio 决定比例，size 决定分辨率桶）
2. width + height（目标尺寸，会近似到模型支持的最接近值）
3. resolution（另一种尺寸写法）
4. size（简写格式）

编辑后的图片会自动保存到 workspace。
    """.strip()

    def __init__(
        self,
        image_models: Dict[str, BaseImageModel],
        model_descriptions: Optional[Dict[str, str]] = None,
        workspace: Optional[TaskWorkspace] = None,
        default_generate_model: Optional[BaseImageModel] = None,
        default_edit_model: Optional[BaseImageModel] = None,
    ):
        """
        Initialize with pre-configured image models.

        Args:
            image_models: Dictionary mapping model_id to BaseImageModel instances
            model_descriptions: Dictionary mapping model_id to description strings
            workspace: Optional workspace for saving generated images
            default_generate_model: Default model for image generation
            default_edit_model: Default model for image editing
        """
        self._image_models = image_models
        self._model_descriptions = model_descriptions or {}
        self._workspace = workspace
        self._default_generate_model = default_generate_model
        self._default_edit_model = default_edit_model
        self._generate_model_info_text()

    def _generate_model_info_text(self) -> None:
        """Generate formatted text with available models and descriptions."""
        if not self._image_models:
            self._model_info_text = "No image models available"
            self._edit_model_info_text = (
                "No image models with edit capabilities available"
            )
            return

        # Get default model IDs for marking
        default_generate_id = None
        if self._default_generate_model:
            default_generate_id = getattr(
                self._default_generate_model, "model_id", None
            ) or getattr(self._default_generate_model, "model_name", None)

        default_edit_id = None
        if self._default_edit_model:
            default_edit_id = getattr(
                self._default_edit_model, "model_id", None
            ) or getattr(self._default_edit_model, "model_name", None)

        # Generate info for generate-capable models only (for generate_image)
        # Put default model first, then others
        default_model_lines = []
        other_model_lines = []
        for model_id, model in self._image_models.items():
            if hasattr(model, "has_ability") and model.has_ability("generate"):
                description = self._model_descriptions.get(model_id, "")
                edit_marker = " ✎" if model.has_ability("edit") else ""
                is_default = model_id == default_generate_id
                default_marker = " ⭐[DEFAULT]" if is_default else ""

                if description:
                    line = f"- {model_id}: {description}{edit_marker}{default_marker}"
                else:
                    line = f"- {model_id}: No description available{edit_marker}{default_marker}"

                if is_default:
                    default_model_lines.append(line)
                else:
                    other_model_lines.append(line)

        model_lines = default_model_lines + other_model_lines
        if model_lines:
            self._model_info_text = "\n".join(model_lines)
        else:
            self._model_info_text = (
                "No image models with generate capabilities available"
            )

        # Generate info for edit-capable models only (for edit_image)
        # Put default model first, then others
        default_edit_lines = []
        other_edit_lines = []
        for model_id, model in self._image_models.items():
            if hasattr(model, "has_ability") and model.has_ability("edit"):
                description = self._model_descriptions.get(model_id, "")
                is_default = model_id == default_edit_id
                default_marker = " ⭐[DEFAULT]" if is_default else ""

                if description:
                    line = f"- {model_id}: {description}{default_marker}"
                else:
                    line = f"- {model_id}: No description available{default_marker}"

                if is_default:
                    default_edit_lines.append(line)
                else:
                    other_edit_lines.append(line)

        edit_model_lines = default_edit_lines + other_edit_lines
        if edit_model_lines:
            self._edit_model_info_text = "\n".join(edit_model_lines)
        else:
            self._edit_model_info_text = (
                "No image models with edit capabilities available"
            )

    def _get_model(self, model_id: Optional[str] = None) -> Optional[BaseImageModel]:
        """Get image model with generate capability by ID or default model."""
        if model_id and model_id in self._image_models:
            model = self._image_models[model_id]
            if hasattr(model, "has_ability") and model.has_ability("generate"):
                return model
            else:
                logger.warning(f"Model {model_id} does not support generation")
                return None

        # Use configured default generate model
        if self._default_generate_model:
            return self._default_generate_model

        # Fallback: return first available model with generate capability
        for model in self._image_models.values():
            if hasattr(model, "has_ability") and model.has_ability("generate"):
                return model

        return None

    def _get_edit_model(
        self, model_id: Optional[str] = None
    ) -> Optional[BaseImageModel]:
        """Get image model with edit capability by ID or default edit model."""
        if model_id and model_id in self._image_models:
            model = self._image_models[model_id]
            if hasattr(model, "has_ability") and model.has_ability("edit"):
                return model
            else:
                logger.warning(f"Model {model_id} does not support editing")
                return None

        # Use configured default edit model
        if self._default_edit_model:
            return self._default_edit_model

        # Fallback: return first available model with edit capability
        for model in self._image_models.values():
            if hasattr(model, "has_ability") and model.has_ability("edit"):
                return model

        return None

    def _resolve_image_path(self, image_input: str) -> str:
        """
        Resolve image input to appropriate format for image model.

        Args:
            image_input: Either a URL string or a local file path

        Returns:
            str: Resolved image path/URL suitable for the image model
        """
        if image_input.startswith("file:") and not image_input.startswith("file://"):
            image_input = image_input[5:].strip()

        # Check if it's a URL (http/https)
        if image_input.startswith(("http://", "https://")):
            return image_input

        # Treat as local file path
        if self._workspace:
            try:
                # Use workspace's resolve_path_with_search method for intelligent directory search
                resolved_path = self._workspace.resolve_path_with_search(image_input)
                logger.info(
                    f"Resolved image path using workspace search: {image_input} -> {resolved_path}"
                )
                return str(resolved_path)
            except ValueError as e:
                logger.warning(f"Cannot resolve image path in workspace: {e}")
                # Fall back to simple path resolution
            except Exception as e:
                logger.warning(f"Error using workspace path resolution: {e}")
                # Fall back to simple path resolution

        # Fallback: simple path resolution (for when workspace is not available)
        image_path = Path(image_input)

        # If it's a relative path, resolve it relative to current working directory
        if not image_path.is_absolute():
            image_path = Path.cwd() / image_path

        # Convert to absolute path string
        absolute_path = str(image_path.resolve())

        # Check if file exists
        if not image_path.exists():
            logger.warning(f"Local image file not found: {absolute_path}")
            # Return the path anyway - the model will handle the error
        else:
            logger.info(
                f"Resolved image path using fallback method: {image_input} -> {absolute_path}"
            )

        return absolute_path

    def _normalize_image_inputs(self, image: str | list[str]) -> list[str]:
        """Normalize image inputs to a non-empty list of strings."""
        if isinstance(image, str):
            if not image:
                raise ValueError("image must be a non-empty string")
            return [image]
        if isinstance(image, list):
            if not image:
                raise ValueError("image list cannot be empty")
            if not all(isinstance(item, str) and item for item in image):
                raise ValueError("All image entries must be non-empty strings")
            return image
        raise ValueError("image must be a string or list of strings")

    async def _download_image(
        self, image_url: str, filename: Optional[str] = None, timeout: int = 30
    ) -> str:
        """
        Download image from URL and save to workspace.

        Args:
            image_url: URL of the image to download
            filename: Optional filename to save as, or save to an auto-generated filename
            timeout: Download timeout in seconds (default: 30)

        Returns:
            Path to the saved image file
        """
        if not self._workspace:
            raise ValueError("No workspace available for saving images")

        # Generate filename if not provided
        extension = ""
        is_data_url = image_url.startswith("data:")
        if is_data_url:
            header, _, _ = image_url.partition(",")
            media_type = (
                header[5:].split(";", 1)[0] if header.startswith("data:") else ""
            )
            extension = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/webp": ".webp",
            }.get(media_type, "")

        if not filename:
            # Extract file extension from URL or default to .png
            url_path = image_url.split("?")[0]  # Remove query parameters
            if not extension:
                extension = os.path.splitext(url_path)[1]
            if not extension:
                extension = ".png"  # Default extension for generated images

            filename = f"generated_image_{uuid.uuid4().hex[:8]}{extension}"

        # Ensure filename is safe
        filename = "".join(c for c in filename if c.isalnum() or c in ("-", "_", "."))

        # Save to output directory
        save_path = self._workspace.output_dir / filename

        try:
            if is_data_url:
                header, _, data = image_url.partition(",")
                if ";base64" in header:
                    content = base64.b64decode(data)
                else:
                    content = parse.unquote_to_bytes(data)
                with open(save_path, "wb") as f:
                    f.write(content)
                logger.info(f"Saved data URL image to: {save_path}")
                return str(save_path)

            local_path = None
            if image_url.startswith("file://"):
                parsed = parse.urlparse(image_url)
                if parsed.scheme == "file":
                    local_path = Path(parse.unquote(parsed.path))
            elif os.path.isabs(image_url) or os.path.exists(image_url):
                local_path = Path(image_url)

            if local_path is not None:
                if not local_path.is_file():
                    raise RuntimeError(f"Local image path is not a file: {local_path}")
                shutil.copyfile(local_path, save_path)
                logger.info(f"Copied local image to: {save_path}")
                return str(save_path)

            # Download the image with configurable timeout
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to download image: HTTP {response.status}"
                        )

                    # Save the image
                    with open(save_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            logger.info(f"Downloaded image to: {save_path}")
            return str(save_path)

        except Exception as e:
            logger.warning(f"Failed to download image from {image_url}: {e}")
            raise

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024*1024",
        negative_prompt: str = "",
        model_id: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Generate an image using the configured image model.

        Args:
            prompt: Text prompt for image generation
            size: Image size in format "width*height" (e.g., "1024*1024")
            negative_prompt: Negative prompt for image generation
            model_id: Specific model ID to use (optional, uses default if not provided)
            width: Image width in pixels (alternative to size)
            height: Image height in pixels (alternative to size)
            resolution: Image resolution (e.g., "1920x1080")
            aspect_ratio: Aspect ratio (e.g., "3:2", "16:9")
            **kwargs: Additional model-specific parameters

        Returns:
            Dictionary with image generation result
        """
        try:
            # Get the image model to use
            image_model = self._get_model(model_id)

            if not image_model:
                return {
                    "success": False,
                    "error": "No available image models configured",
                    "image_path": None,
                }

            # Build parameters for image generation
            generate_params: dict[str, Any] = {
                "prompt": prompt,
                "size": size,
                "negative_prompt": negative_prompt,
            }

            # Add optional parameters if provided
            if width is not None:
                generate_params["width"] = width
            if height is not None:
                generate_params["height"] = height
            if resolution is not None:
                generate_params["resolution"] = resolution
            if aspect_ratio is not None:
                generate_params["aspect_ratio"] = aspect_ratio

            # Add any additional kwargs
            generate_params.update(kwargs)

            # Generate the image
            result = await image_model.generate_image(**generate_params)

            # Determine the actual model used
            actual_model_id = (
                model_id if model_id and model_id in self._image_models else "default"
            )

            image_url = result.get("image_url")
            image_path = None
            image_file_id: Optional[str] = None

            # Download image to workspace if workspace is available
            if image_url and self._workspace:
                try:
                    with self._workspace.auto_register_files():
                        image_path = await self._download_image(image_url)
                        if image_path:
                            image_file_id = self._workspace.get_file_id_from_path(
                                image_path
                            )
                except Exception as e:
                    logger.warning(f"Failed to download image to workspace: {e}")
                    # Continue execution even if download fails
            elif image_url and not self._workspace:
                logger.warning("No workspace available, image not saved locally")

            return {
                "success": True,
                "image_path": image_path,
                "file_id": image_file_id,
                "usage": result.get("usage", {}),
                "task_metric": result.get("task_metric", {}),
                "request_id": result.get("request_id"),
                "model_used": actual_model_id,
                "saved_to_workspace": image_path is not None,
            }

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            # Determine the actual model used for error reporting
            actual_model_id = (
                model_id if model_id and model_id in self._image_models else "default"
            )
            return {
                "success": False,
                "error": str(e),
                "image_path": None,
                "model_used": actual_model_id,
            }

    async def edit_image(
        self,
        prompt: str,
        image_url: str | list[str],
        negative_prompt: str = "",
        model_id: Optional[str] = None,
        size: str = "1024*1024",
        width: Optional[int] = None,
        height: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Edit an image using the configured image model.

        Args:
            image_url: URL/path of a single source image to edit, or list of URLs/paths
            prompt: Text prompt describing the desired edits
            negative_prompt: Negative prompt for image editing
            model_id: Specific model ID to use (optional, uses first available edit-capable model if not provided)
            size: Image size in format "width*height" (e.g., "1024*1024")
            width: Image width in pixels (alternative to size)
            height: Image height in pixels (alternative to size)
            resolution: Image resolution (e.g., "1920x1080")
            aspect_ratio: Aspect ratio (e.g., "3:2", "16:9")
            **kwargs: Additional model-specific parameters

        Returns:
            Dictionary with image editing result
        """
        try:
            # Get the image model to use
            image_model = self._get_edit_model(model_id)

            if not image_model:
                return {
                    "success": False,
                    "error": "No available image models with edit capabilities",
                    "image_path": None,
                }

            image_inputs = self._normalize_image_inputs(image_url)
            resolved_image_paths = [
                self._resolve_image_path(image_input) for image_input in image_inputs
            ]
            logger.info(
                f"Resolved image paths: {image_inputs} -> {resolved_image_paths}"
            )

            # Build parameters for image editing
            edit_params: dict[str, Any] = {
                "image_url": resolved_image_paths[0]
                if len(resolved_image_paths) == 1
                else resolved_image_paths,
                "prompt": prompt,
                "size": size,
                "negative_prompt": negative_prompt,
            }

            # Add optional parameters if provided
            if width is not None:
                edit_params["width"] = width
            if height is not None:
                edit_params["height"] = height
            if resolution is not None:
                edit_params["resolution"] = resolution
            if aspect_ratio is not None:
                edit_params["aspect_ratio"] = aspect_ratio

            # Add any additional kwargs
            edit_params.update(kwargs)

            # Edit the image
            result = await image_model.edit_image(**edit_params)

            # Determine the actual model used
            actual_model_id = model_id if model_id else "default_edit_model"

            edited_image_url = result.get("image_url")
            image_path = None
            image_file_id: Optional[str] = None

            # Download image to workspace if workspace is available
            if edited_image_url and self._workspace:
                try:
                    # Use a different filename pattern for edited images
                    filename = f"edited_image_{uuid.uuid4().hex[:8]}.png"
                    with self._workspace.auto_register_files():
                        image_path = await self._download_image(
                            edited_image_url, filename
                        )
                        if image_path:
                            image_file_id = self._workspace.get_file_id_from_path(
                                image_path
                            )
                except Exception as e:
                    logger.warning(f"Failed to download edited image to workspace: {e}")
                    # Continue execution even if download fails
            elif edited_image_url and not self._workspace:
                logger.warning("No workspace available, edited image not saved locally")

            return {
                "success": True,
                "image_path": image_path,
                "file_id": image_file_id,
                "usage": result.get("usage", {}),
                "task_metric": result.get("task_metric", {}),
                "request_id": result.get("request_id"),
                "model_used": actual_model_id,
                "saved_to_workspace": image_path is not None,
            }

        except Exception as e:
            logger.error(f"Image editing failed: {e}")
            # Determine the actual model used for error reporting
            actual_model_id = model_id if model_id else "default_edit_model"
            return {
                "success": False,
                "error": str(e),
                "image_path": None,
                "model_used": actual_model_id,
            }

    def list_available_models(self) -> Dict[str, Any]:
        """
        List all available image models.

        Returns:
            Dictionary with available models information including descriptions
        """
        try:
            models_info = []
            for model_id in self._image_models.keys():
                model_info = {
                    "model_id": model_id,
                    "available": True,
                    "description": self._model_descriptions.get(model_id, ""),
                }
                models_info.append(model_info)

            return {
                "success": True,
                "models": models_info,
                "count": len(models_info),
            }

        except Exception as e:
            logger.error(f"Failed to list available models: {e}")
            return {
                "success": False,
                "error": str(e),
                "models": [],
                "count": 0,
            }
