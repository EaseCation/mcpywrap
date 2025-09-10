# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言说明

- 使用中文进行沟通
- 代码注释中使用中文进行注释

## 项目概述

mcpywrap 是一个用于《我的世界》中国版 ModSDK/资源包的全周期管理工具，基于 Python 生态系统构建。项目支持：
- Minecraft Addon（插件）开发和构建
- Minecraft Map（地图）项目管理
- 依赖包管理和模块化开发
- 与 MC Studio 的深度集成

## 常用命令

### 开发命令
```bash
# 安装项目到开发环境（可编辑模式）
pip install -e .

# 初始化新项目
mcpy init

# 构建项目到 MCStudio 工程
mcpy build
mcpy build --merge  # 强制合并所有资源文件

# 开发模式（watch模式，实时构建与热重载）
mcpy dev

# 运行游戏实例
mcpy run
mcpy run -n          # 创建新实例
mcpy run -l          # 列出所有实例
mcpy run -d <prefix> # 删除指定实例

# 使用 MC Studio 编辑器
mcpy edit

# 创建 Python Mod 模板
mcpy mod
```

### 依赖管理
```bash
# 添加依赖包
mcpy add <package> [version]

# 移除依赖包
mcpy remove <package>
```

### 发布
```bash
# 发布到 PyPI
mcpy publish
```

## 核心架构深度解析

### 项目结构
- `mcpywrap/` - 主包目录
  - `cli.py` - Click CLI 入口点
  - `commands/` - 所有CLI命令实现
  - `builders/` - 项目构建器（AddonsPack, MapPack, 依赖管理）
  - `minecraft/` - Minecraft相关功能（addons, map, template）
  - `mcstudio/` - MC Studio 集成（game, symlinks, runtime配置）
  - `utils/` - 工具函数和项目设置
  - `ui/` - PyQt5 用户界面组件

### 关键组件详解

#### 1. 依赖管理系统 (builders/dependency_manager.py)
- **DependencyManager**: 核心依赖管理器
  - 支持 `pip install -e` 安装的开发包发现
  - 通过 `direct_url.json` 解析本地包路径
  - 构建递归依赖树，处理依赖的依赖关系
  - 防止循环依赖的机制
- **DependencyNode**: 依赖树节点，支持层次化依赖解析
- **find_all_mcpywrap_packages()**: 自动发现系统中所有 mcpywrap 兼容包

#### 2. 包构建系统 (builders/)
- **AddonsPack**: 
  - 处理行为包和资源包的复制、合并操作
  - 智能文件过滤（排除 Python 包管理文件）
    - 支持 manifest.json 冲突处理
- **MapPack**:
  - 地图存档数据管理（level.dat, levelname.txt, db/）
  - 资源包和行为包目录管理
  - 自动生成 world_behavior_packs.json 和 world_resource_packs.json

#### 3. 文件监控系统 (builders/watcher.py)
- **ProjectWatcher**: 项目级文件监控
  - 同时监控主项目和所有依赖项目
  - 智能文件变化处理（创建、修改、删除、移动）
  - 支持热重载，文件变化时自动重新合并
- **FileChangeHandler**: 
  - 基于 watchdog 库的文件系统事件处理
  - 冷却机制防止重复处理相同事件
  - 支持软链接和临时文件过滤

#### 4. 文件合并系统 (builders/file_merge.py)
- 智能 JSON 文件合并：
  - `terrain_texture.json`, `item_texture.json` (texture_data 字段合并)
  - `sounds.json`, `sound_definitions.json` (sound_definitions 合并)
  - `animations.json`, `animation_controllers.json` (动画数据合并)
  - `_ui_defs.json` (UI 定义去重合并)
- .lang 文件键值对合并
- 图片文件冲突警告和覆盖机制

#### 5. MC Studio 集成系统 (mcstudio/)

##### 软链接管理 (symlinks.py)
- **setup_global_addons_symlinks()**: 全局插件软链接
  - Windows 管理员权限自动提权
  - 清理旧链接 → 创建新链接的原子操作
  - 支持多包同时链接，避免命名冲突
- **setup_map_packs_symlinks()**: 地图专用软链接
  - 运行时地图目录软链接到源代码目录
  - 支持行为包和资源包目录级别的链接

##### 游戏实例管理 (game.py)
- **open_game()**: 
  - 自动检测和选择 MC Studio 引擎版本
  - 从注册表读取 MC Studio 安装信息
  - 启动游戏进程并应用 Windows 主题样式
- **apply_system_titlebar_style()**: 
  - Windows 11 Mica 效果和深色主题支持
  - DWM API 调用优化窗口外观
- **open_safaia()**: 启动 Safaia Server 日志工具

##### 运行时配置 (runtime_cppconfig.py)
- **gen_runtime_config()**: 
  - 生成 MC Studio 兼容的 .cppconfig 文件
  - 包含世界信息、游戏设置、作弊选项
  - 行为包和资源包链接配置

##### 日志服务器 (studio_server.py)
- **StudioLogServer**: 多线程日志接收服务器
  - 支持命令行和 PyQt5 UI 模式
  - 智能日志着色（ANSI 终端色彩 + Qt 富文本）
  - 命令历史记录和客户端管理
  - JSON 命令消息解析和处理

#### 6. MC Studio 系统集成 (mcstudio/mcs.py)
- 从 Windows 注册表读取 MC Studio 配置：
  - `get_mcs_download_path()`: 下载路径
  - `get_mcs_install_location()`: 安装路径
  - `get_mcs_game_engine_dirs()`: 引擎版本目录（按版本排序）
  - `get_mcs_game_engine_data_path()`: 用户数据路径

### 项目类型支持

#### Addon 项目架构
- **behavior_pack/**: 行为包（脚本逻辑、实体定义、物品定义等）
- **resource_pack/**: 资源包（纹理、模型、声音、UI 等）
- 支持依赖层次化合并：深层依赖先合并，浅层依赖后合并

#### Map 项目架构
- **地图核心文件**: level.dat, levelname.txt, db/
- **behavior_packs/**: 地图专用行为包
- **resource_packs/**: 地图专用资源包
- 强制合并模式支持（--merge 参数）
- 自动生成包配置文件（从 manifest.json 提取 UUID 和版本）

### 配置系统

#### pyproject.toml 结构
```toml
[project]
name = "project-name"
version = "0.1.0"
dependencies = ["other-mcpywrap-package>=1.0.0"]

[tool.mcpywrap]
project_type = "addon"     # "addon" 或 "map"
target_dir = "./build"     # 构建输出目录
```

### 依赖解析机制

1. **包发现**: 扫描 site-packages 中的 *.dist-info 目录
2. **路径解析**: 读取 direct_url.json 获取本地开发包路径
3. **递归依赖**: 解析每个包的 pyproject.toml 获取子依赖
4. **依赖树构建**: 构建完整的依赖关系树
5. **层次化处理**: 按依赖层次顺序合并文件

### 热重载开发流程

1. `mcpy dev` 启动监控模式
2. 初始构建项目到目标目录
3. 启动 **ProjectWatcher** 监控源码和所有依赖
4. 文件变化时：
   - 识别文件属于哪个包（主项目或依赖）
   - 确定文件类型（行为包/资源包）
   - 计算目标文件路径
   - 执行智能合并（覆盖或深度合并）
5. 实时反馈处理结果

### 游戏实例管理

- **.runtime/** 目录存储实例配置
- **level_id**: UUID 格式的世界唯一标识符
- **实例配置文件**: {level_id}.cppconfig
- **软链接机制**: 避免文件拷贝，支持热更新
- **多实例支持**: 可同时管理多个游戏世界

### Windows 系统集成

- **注册表访问**: 自动发现 MC Studio 安装信息
- **管理员权限**: 软链接创建时自动提权
- **进程管理**: 游戏进程启动和窗口样式控制
- **DWM API**: Windows 11 现代化窗口效果

### 测试和调试

项目无自动化测试，依赖实际运行验证：
- `mcpy run` - 启动游戏实例验证功能
- `mcpy dev` - 热重载测试开发工作流
- **Safaia Server** - 游戏内日志和调试命令
- **StudioLogServer** - 彩色日志输出和命令控制

### 开发最佳实践

1. **依赖管理**: 使用 `mcpy add/remove` 管理依赖，避免手动编辑 pyproject.toml
2. **开发模式**: 优先使用 `mcpy dev` 进行开发，充分利用热重载
3. **文件组织**: 遵循标准的 behavior_pack/resource_pack 目录结构
4. **日志调试**: 使用日志服务器监控游戏运行状态和脚本输出