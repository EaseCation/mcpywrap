# 维护者：开发与验证

```powershell
python -m unittest discover -s tests -v
```

自动化测试使用临时目录、模拟安装/发布、Qt 离屏界面和模拟游戏进程，不启动真实游戏。
CLI 使用调用上下文传递项目目录；底层服务接受明确路径。不要为 GUI 切换全局工作目录。

有限命令返回数据或抛出错误，公共 CLI 层负责 JSON、stderr 和退出码。
新增命令使用相同入口，避免打印错误后返回成功。

Skill 的 bootstrap、smoke 脚本只使用公开 CLI；Skill 的 game_window 脚本负责绑定会话的截图和键盘输入；复杂交互使用环境的 Computer Use。
真实游戏验证请使用独立测试项目：

```powershell
python skills/mcpywrap/scripts/smoke.py --project D:\mods\test --game --expect-log "服务端已加载" --expect-log "客户端已加载"
```

脚本结束后停止自己创建的会话；日志和产物留在项目中。
需要手动截图验证时直接运行 `run --no-gui --detach --json`，保存会话 ID，操作完后显式 stop。
网络验证使用 `smoke.py --project <已有目录> --connect <地址> --expect-log <约定标记>`，不打包项目。单人与网络测试都可显式加 `--mcs-auth`；脚本停止自己创建的会话。
历史验收记录仅用于追溯，不能代替当前版本测试。

发布见 [发布流程](releasing.md)。
