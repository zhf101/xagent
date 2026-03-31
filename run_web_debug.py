"""PyCharm 脚本调试入口。

这个文件的存在只有一个目的：
- 让 PyCharm 在 `Python script` 模式下也能正确启动 `xagent.web`

原因：
- `src/xagent/web/__main__.py` 依赖包上下文中的相对导入
- 直接把 `__main__.py` 当脚本执行时，会触发
  `ImportError: attempted relative import with no known parent package`

因此这里改为先通过绝对导入拿到 `main()`，再作为普通脚本调用。
"""

from xagent.web.__main__ import main


if __name__ == "__main__":
    main()
