# 示例：CSV 生成游戏包数据

仅在需要编写生成器时读本页；配置与触发时机见[项目脚本](project-scripts.md)。

原始素材放在包外，最终业务文件放在已有行为包内。例如 `data/items.csv`：

```csv
id,value
apple,5
stone,2
```

`tools/assets.py` 是宿主 Python 3 脚本：

```python
import csv
import json
import os
from pathlib import Path
import tempfile

root = Path(os.environ["MCPY_PROJECT_ROOT"])
with (root / "data/items.csv").open(encoding="utf-8", newline="") as stream:
    rows = list(csv.DictReader(stream))
items = {row["id"]: int(row["value"]) for row in rows}
if len(items) != len(rows):
    raise ValueError("重复的物品 ID")

# 先完成生成与校验，再替换一个最终文件；临时文件不放进游戏包。
target = root / "behavior_pack/MyMod/generated/items.json"
target.parent.mkdir(parents=True, exist_ok=True)
scratch = root / ".mcpy/asset-temp"
scratch.mkdir(parents=True, exist_ok=True)
fd, name = tempfile.mkstemp(dir=scratch, suffix=".json")
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(items, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    os.replace(name, target)
finally:
    Path(name).unlink(missing_ok=True)
```

对应任务只需 `python = "tools/assets.py"`，不要照抄上文示例的 `--quality` 参数，除非脚本实现了参数解析。生成多个文件时应由脚本负责删除不再需要的旧输出。Python 3 工具代码放在 tools，不放入行为包；生成的游戏业务脚本仍须兼容目标引擎，不能依赖临时调试 `mcpy.*`。
