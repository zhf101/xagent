"""PyCharm 脚本调试入口。

这个文件的存在只有一个目的：
- 让 PyCharm 在 `Python script` 模式下也能正确启动 `xagent.web`

原因：
- `src/xagent/web/__main__.py` 依赖包上下文中的相对导入
- 直接把 `__main__.py` 当脚本执行时，会触发
  `ImportError: attempted relative import with no known parent package`

因此这里改为先通过绝对导入拿到 `main()`，再作为普通脚本调用。
"""
"""
修复 PyCharm Debug Uvicorn loop_factory 兼容性问题
"""
import sys
import asyncio
from xagent.web.__main__ import main

def fix_pycharm_uvicorn_loop_factory():
    """修复 PyCharm debug 下 uvicorn 的 loop_factory 报错"""
    if sys.gettrace() is not None:  # 调试模式
        try:
            run_qualname = asyncio.run.__qualname__
            if "_patch_asyncio" in run_qualname:
                # 保存原生 run
                original_run = asyncio.run

                # 包装：忽略 loop_factory
                def wrapped_run(main, *, debug=False, loop_factory=None, **kwargs):
                    return original_run(main, debug=debug)

                asyncio.run = wrapped_run
                print("✅ 已修复 PyCharm Debug + Uvicorn loop_factory 兼容性问题")
        except AttributeError:
            pass

# 必须先执行修复
fix_pycharm_uvicorn_loop_factory()

if __name__ == "__main__":
    main()
