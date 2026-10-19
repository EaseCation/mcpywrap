# 测试入口

仓库通用开发与验证约定见 [CONTRIBUTING.md](../CONTRIBUTING.md)。默认自动化使用临时文件、真实有限子进程、模拟游戏调用端与回环服务，不启动真实游戏：

```text
python -X utf8 -m unittest discover -s tests -v
```

测试结果、环境信息和单次验收报告保存在 Git 忽略的 `.local-notes/`、`test/` 或 `.runtime/`，不放入 docs 或分发包。Windows 与 macOS 的实机结果分别记录；跳过不算通过。

## 输入编排

`test_input_sequence.py`、`test_runtime_key_timeline.py`、`test_runtime_input.py` 验证时序、快照、取消、幂等和释放；兼容入口还需运行 `test_game_window_skill.py`、`test_mouse.py` 和真实回环协议测试 `test_remote.py`。

交互式 Windows 桌面显式设置 `MCPY_NATIVE_TESTS=1` 后可运行 `test_native_input_sequence.py`，只创建自己的接收窗口，检查 0/1/5/10/20 ms 的提交和接收顺序。`MCPY_INPUT_TEST_REPORT` 可指定新的报告路径；系统调度抖动应保留到结果中。

真实游戏使用 `manual_runtime_input.py --project <独立测试项目> --session <sid> --output <新JSON>`。需要已加载 HUD、快捷栏 8/9 为空并朝向无目标天空；会占用前台，随后恢复原选槽和朝向。`manual_runtime_key_timeline.py` 检查后台重叠按键、修饰键顺序及取消。脚本不会停止传入会话，由创建者清理。

## UI、玩家与世界

`test_runtime_ui.py`、`test_runtime_ui_outline.py` 验证快照、分组、输入归属和 UI 操作状态；`test_runtime_player.py` 验证选槽、移动、使用物品、队列和业务状态检查。可选实机程序与服务端夹具见 [runtime_controls](manual/runtime_controls/README.md)。只有客户端 completed 不足以证明服务端效果。

世界配置检查须覆盖保存后重开、生成器、种子、模式、难度、规则及实例隔离；各平台按自己的游戏环境执行。录制、后台采集等需要可见桌面的测试不进入默认执行路径，具体参数见对应 `manual_*.py --help`。

## 依赖与资源准备

`test_git_projects.py` 使用真实本地 Git 验证固定提交、导出、传递关系、缓存、锁和更新回退；游戏对第三方框架的兼容性需要单独确认。

`test_consumer_prepare.py` 覆盖本地/Git 准备入口、工具环境、只读计划、配置校验和生命周期；其中的独立 Skill 模板测试不依赖仓库外层示例。可选程序 `manual/consumer_prepare_acceptance.py --output <新目录>` 默认只验证资源准备，显式加 `--game` 才启动测试游戏，`--clients 2` 检查主机/客机准备次数。保留报告和世界，脚本只停止自己的测试会话。
