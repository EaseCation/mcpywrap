# 固定版本游戏代码库

代码库由构建工具装入游戏包，独立于 `[project].dependencies`（工具 Python 环境）和 `local_dependencies`（完整 Addon）。不要求上游包含 manifest，不运行上游安装脚本，不自动初始化入口。

```toml
[[tool.mcpywrap.code_libraries]]
name = "qumod"
git = "https://github.com/GitHub-Zero123/QuModLibs.git"
rev = "a07430aaaa6dce5f1ef68de3fda52ea4b9366c2c"
subdir = "Scripts/QuModLibs"
target = "OreDetector/QuModLibs"
```

`target` 相对行为包；声明代码库的 Addon 须有行为包及 manifest。路径用 `/`，不得越界。每个条目必须包含上述五个字段。支持 HTTPS 或 `file:///...` 本地 Git 仓库；`rev` 必须是完整40位小写提交，不接受浮动分支。目标不能与手写目录、同名 Python 模块或其他库重叠。

运行 `mcpy sync` 显式获取库，缓存于项目 `.mcpy/libraries/`，写出 `mcpy-code-libraries.lock.json`（声明与内容 SHA-256）。将 `.mcpy/`、`.runtime/`、`build/`、`dist/` 加入 Git 忽略，提交配置与锁文件，不提交上游源码。根目录 LICENSE/COPYING/NOTICE 随库保存。`sync --install` 还会进行原有的工具环境安装；安装游戏库不需要这个参数。

`build`、`package` 和 `run` 只消费已同步且通过摘要检查的库；没有缓存时先 `sync`。更新 `rev` 后重新同步，按完整目录替换产物，旧文件不会遗留。回退改回旧提交并同步。不删除旧缓存；损坏缓存报错，不静默覆盖。锁文件与预期内容必须一致，校验和并不等于上游作者身份认证。

带代码库的 Addon 在 `run` 前组装到 `.mcpy/runtime/assembled`；配置、引擎选择、世界和会话仍属于原项目。发布 ZIP 使用同一组装逻辑。游戏内修改原源码不会自动刷新运行产物，重新 `run` 会重建；持续开发可用 `mcpy dev` 更新配置的构建目录。`dev` 遇到代码库项目采用完整原子组装，修改依赖声明后应同步并重启监控。不要把“重建文件”理解为正在运行的游戏会自动重载 Python。

QuMod 示例入口：

```python
# -*- coding: utf-8 -*-
# QMain 必须保留在 modMain 的命名空间，供网易加载器发现绑定类。
from .QuModLibs.QuMod import EasyMod, QMain
MOD = EasyMod()
MOD.Server('Server')
MOD.Client('Client')
```

同一 Mod 的功能模块共享它的 QuMod；独立 Mod 各自安装到独立脚本根。不能仅按库版本全局合并实例，QuMod 的系统名和通信通道依赖脚本根命名空间。原版 API 与框架生命周期仍需在目标游戏中验证。

范围：固定源码获取和组装；不解析库内部传递依赖、不求解版本范围、不自动裁剪 QuMod、不提供中央仓库或游戏内下载。地图自身不声明代码库，可引用包含代码库的 Addon。离线构建需要已经同步的缓存；干净机器运行 sync 恢复相同提交与摘要。
