"""仓库根目录下的 `xagent` 入口 shim。

这个文件专门解决当前仓库采用 `src/` 布局时，一个非常常见但又很隐蔽的问题：

1. 开发者站在仓库根目录执行 `python -m xagent.web`
2. Python 默认不会自动把 `src/` 加进 `sys.path`
3. 如果当前环境里还安装过别的 `xagent`（比如旧仓库 editable install、site-packages 版本）
4. 那么解释器就可能导入到“别的 xagent”，导致：
   - 代码改了但运行结果没变
   - `.env` 看起来像没生效
   - 日志、迁移、向量后端全都指向旧环境

因此这里放一个极轻量的 shim，让“仓库根目录优先”这个直觉行为真正成立：
- 当前目录存在这个 `xagent` 包时，先命中它
- 再把 `src/xagent` 显式追加到包搜索路径
- 后续 `xagent.web` / `xagent.config` 等子模块就会从当前仓库源码解析

它不负责导出业务 API，也不做复杂初始化，职责只有一个：
确保从仓库根目录执行模块命令时，导入的就是这份源码。
"""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

# 先保留 namespace package 语义，避免破坏已有安装方式。
__path__ = list(extend_path(__path__, __name__))  # type: ignore[name-defined]

# 再把当前仓库的 `src/xagent` 放进包搜索路径前列。
# 这样 `python -m xagent.web` 从仓库根目录启动时，会稳定落到这份源码，
# 而不是误命中 site-packages 或其他 worktree 里的旧版 xagent。
_repo_src_package = Path(__file__).resolve().parents[1] / "src" / "xagent"
if _repo_src_package.is_dir():
    repo_src_package_str = str(_repo_src_package)
    # 顺序必须足够激进：
    # - 当前 shim 自己所在目录保留在最前，确保先命中这个包
    # - 当前仓库的 `src/xagent` 紧随其后，确保子模块优先解析到这份源码
    # - 其余 site-packages / 其他 worktree 路径放后面，仅作兼容兜底
    __path__ = [
        path
        for path in __path__
        if path != repo_src_package_str
    ]
    __path__.insert(1 if __path__ else 0, repo_src_package_str)
