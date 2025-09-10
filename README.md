# 🧰 mcpywrap 

**《我的世界》中国版 ModSDK 与资源包的全周期管理工具**

[![PyPI Version](https://img.shields.io/pypi/v/mcpywrap)](https://pypi.org/project/mcpywrap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

mcpywrap 是基于 Python 生态的《我的世界》中国版 ModSDK/资源包全周期管理工具，支持依赖管理、语法转换和自动化构建，助力开发者实现高效协作与代码复用。

## 🌟 核心特性

- 🧩 **模块化开发** - 基于 Addons 维度的依赖管理（基于包管理和依赖的开发与测试流程）
- 🔄 **现代语法** - 支持 Python3 现代语法特性，提升开发体验
- 📦 **生态兼容** - 无缝对接 PyPI 生态，支持标准 `pyproject.toml` 配置
- 🚀 **智能构建** - 一键打包符合 MCStudio 规范的成品 Addons
- 🔥 **热重载开发** - 实时监控代码变更，支持 MCStudio 热更新

## 📖 为何选择此工具？

### 传统开发痛点
- 📜 **代码复用困难** - 通过 **文件拷贝** 导致版本管理混乱
- 🚧 **协作效率低下** - 多项目 **重复代码** 维护成本高
- ⚠️ **代码质量** - 缺乏现代开发工具和语法支持

### mcpywrap 解决方案
1. **标准化开发**  
通过 `pyproject.toml` 声明项目元数据和依赖关系，实现真正的模块化开发

2. **直接启动测试和编辑**  
- 直接通过 `mcpy run` 启动游戏实例，支持热重载和实时构建，提升开发效率
- 通过 `mcpy edit` 命令，使用 MC Studio Editor 编辑器进行编辑

3. **生态集成**  
依托 pip 包管理体系，支持依赖的版本锁定和自动解析


## 🚀 快速开始

### 前置要求
- Python ≥ 3.8
- pip ≥ 21.0

### 安装
```bash
pip install mcpywrap
```

### 初始化项目
```bash
# 首先进入项目目录
mcpy init
```
交互式创建项目结构，自动生成标准的 Mod 框架。

### 运行测试
```bash
mcpy run
```

## 🛠 工作流指南

### 依赖管理
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy`                 | 维护项目，将项目安装到系统 site-package 环境            |
| `mcpy add <package> [version]` | 添加指定版本依赖          |
| `mcpy remove <package>`        | 移除依赖               |

### 完整命令参考

```bash
mcpy --help
```

#### 依赖管理
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy add <package> [version]` | 添加指定版本依赖并安装到项目中 |
| `mcpy remove <package>`        | 从项目配置中删除依赖并可选择卸载 |

#### 项目初始化与开发
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy init`                   | 交互式初始化项目，创建基础的包信息及配置 |
| `mcpy mod`                    | 向导式创建 Python Mod 基础框架 |
| `mcpy build`                  | 构建为 MCStudio 工程 |
| `mcpy dev`                    | 使用watch模式，实时构建与热重载 |
| `mcpy edit`                   | 使用 MC Studio Editor 编辑器进行编辑 |

#### ModSDK与游戏实例
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy modsdk`                 | 管理网易我的世界ModSDK |
| `mcpy run`                    | 游戏实例运行与管理 |

#### 发布项目
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy publish`                | 发布项目到 PyPI |

#### 游戏实例管理详解

```bash
# 启动最新游戏实例
mcpy run

# 创建新的游戏实例
mcpy run -n

# 列出所有可用的游戏实例
mcpy run -l

# 删除指定的游戏实例
mcpy run -d <实例ID前缀>
```

## 🤝 参与贡献
欢迎提交 Issue 和 PR！请先阅读 [贡献指南](CONTRIBUTING.md)。

## 开源协议
[MIT License](LICENSE) © 2025 EaseCation
