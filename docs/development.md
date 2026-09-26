# 开发与验证

```powershell
python -m unittest discover -s tests -v
```

自动化测试使用临时目录、Click、Qt 离屏及安装／启动替身。本机多项目验收脚本另行执行真实 CLI、pip、watchdog，可加 `--game` 启动已安装的 MCS 引擎。请先关闭已有游戏，使用独立环境和一个尚不存在的输出目录：

```powershell
uv venv test/acceptance-venv
uv pip install --python test/acceptance-venv/Scripts/python.exe -e . pip
test/acceptance-venv/Scripts/python.exe tests/manual_integration.py --workspace test/my-acceptance --game
```

脚本保留测试项目、构建结果、CLI/pip 日志和 `report.json`；实际游戏验证检查各 Mod 的服务端／客户端加载标记及游戏生成的包 UUID 列表，并清理本次创建的全局链接。测试存档和 `.runtime` 配置保留供复查。游戏验收仅替换日志窗口为 TCP 文件收集器，真实引擎、目录链接和运行配置均使用产品实现。
