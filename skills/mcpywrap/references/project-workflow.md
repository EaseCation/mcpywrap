# 项目创建、构建与分发

用于源码项目和离线产物。以下都是调用端命令，即使配置 remote 也不会在服务端运行。统一使用 `mcpy --project <已有目录> --non-interactive`，有限命令加 --json。

## 从当前项目状态开始

| 需求 | 命令 | 注意 |
|---|---|---|
| 新空项目 | `init --name demo --type addon` 或 `--type map` | 不覆盖现有配置，不自动安装 SDK/依赖 |
| 刚克隆已有项目 | `sync` | 不重做 init；依赖种类与锁规则见[依赖](project-dependencies.md) |
| 原生 Mod 模板 | `mod --name DemoMod --script-dir DemoScript` | 保留用户已有入口；需要 QuMod 直接走依赖页的快捷流程 |
| ModSDK 补全库 | `modsdk --list` / `--version <目标版本>` / `--latest` | 默认安装到工具环境；`--python <绝对解释器路径>` 定向安装到开发环境，不向游戏安装库 |
| 构建工程 | `build`，地图可加 `--merge` | 需要 tool.mcpywrap.target_dir；不能指向受管运行目录 |
| 持续离线构建 | `dev` | 仅 Addon，持续文本、不加 --json；不是游戏热更 |
| 游戏分发 ZIP | `package`，地图可加 `--merge` | 返回 artifact；无需 target_dir |
| Python 分发 | `publish --yes` | 仅用户要求真实上传时执行；使用 Twine 凭据，不是游戏 ZIP 上传 |
| 人工项目页 / MCEditor | `ui` / Windows `edit --detach` | AI 使用参数 CLI；MCEditor 使用独立准备目录，原生保存回源码仍须验收 |

构建遵守主项目优先的既有合并规则。工具 Python 环境与游戏内 Python 相互独立；add/sync --install/modsdk 不会让游戏读取 site-packages。原生扩展或未适配的 Python 代码不能仅凭 pip 安装成功当作游戏依赖。

项目声明了 hooks 时，build/package/dev 初次构建会执行相应宿主脚本；支持[消费者准备](consumer-prepare.md)的依赖还会在根任务后处理素材。支持该能力的 CLI 可用 `script list --effective --json` 查看完整计划，并检查 complete/ready；仅查根任务用 `script list --json`。根任务配置见[项目脚本](project-scripts.md)，不要从 Python 的 project.scripts 推断生命周期。

## 游戏 ZIP

`package` 生成 `dist/<project.name>-<project.version>.zip`：Addon 内为实际存在的 `<name>_bp/`、`<name>_rp/`；Map 根目录含世界数据及包，默认保留独立包，--merge 合并依赖资源。打包排除规则见[unbundled](project-dependencies.md#不随构建打包unbundled)；普通工具 Python 包不进入游戏包。

使用公开 package 导出，不自行重压缩或改包名。检查返回的 artifact 及实际 ZIP；行为包 `entities/` 空目录会保留，纯脚本项目不需要虚构实体。新 ZIP 成功后替换同名产物，失败保留旧 ZIP；这不代表脚本对源码的写入也会回滚。

产物完整、游戏加载和网易平台验收分别确认。构建成功或上传响应成功不能证明正式玩法正确，也不能替代平台自测。需要运行验证再读[本地会话](local-development.md)。

## dev 与运行部署的区别

dev 维护配置的离线构建目录，包含 unbundled 依赖；源码变化不会因此自动注入游戏。停止 dev 后再让 build 写同一目标；build 会完整替换输出，package 独立组装发布包。实际游戏更新用 runtime reload/watch，见[运行时调试](runtime-debug.md)。依赖声明改变后重新 sync（需要获取时）并重启 dev；不要把 target_dir 改成 `.mcpy/runtime` 或 `.runtime` 绕过部署保护。

游戏世界数据由实例保存。build/package 产物、当前运行部署、世界存档是不同对象；离线打包不应删除或重建测试世界。共享部署占用、重新启动和失败处理见[本地生命周期](local-development.md)。

具体玩法的 API/事件/JSON 组件要查目标网易 ModSDK 版本；不要套用 Java 版或通用 Bedrock 的同名接口。mcpywrap 只负责工程与测试流程，不证明业务 API 兼容。

## 明确 ModSDK 补全库的 Python 环境

有多个 Python 时，先在编辑器中确认实际选用的解释器，再用其完整调用路径检查。不要将 `.venv/bin/python` 的链接解析成系统 Python。

```sh
mcpy --local --project <项目绝对目录> --non-interactive modsdk --inspect --python <Python可执行文件绝对路径> --json
mcpy --local --project <项目绝对目录> --non-interactive modsdk --version <目标版本> --python <同一Python绝对路径> --expected-environment <inspect返回的environment.identity> --json
```

`--inspect` 只读且不联网，不导入 SDK；返回解释器、Python 版本、环境前缀、identity 及已安装包的版本/位置。`installed.in_environment=false` 表示只是在继承路径可见，尚未装入此环境。显式安装由 mcpy 自身的 pip 定向处理，目标环境无需预装 pip；保留 Python 3 强制兼容补全数据的能力，源码无需在宿主 Python 导入或编译。安装前后检查身份和安装位置，失败不回退其他环境，不使用 `--break-system-packages`。

无 `--python` 的旧安装命令继续安装到 mcpy 工具环境；这不一定是 VS Code/Pylance 选中的环境。VS Code 插件使用公开 Python 环境 API 传递资源作用域，不能用默认解释器设置或终端 `(base)` 推断选择；运行时游戏 Python 与宿主开发环境独立。
