# 🧰 mcpywrap 

**《我的世界》中国版 ModSDK 与资源包的全周期管理工具**

[![PyPI Version](https://img.shields.io/pypi/v/mcpywrap)](https://pypi.org/project/mcpywrap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

mcpywrap 是基于 Python 生态的《我的世界》中国版 ModSDK/资源包全周期管理工具，支持依赖管理、语法转换和自动化构建，助力开发者实现高效协作与代码复用。

## 🌟 核心特性

- 🧩 **模块化开发** - 基于 Addons 维度的依赖管理
- 🔄 **语法无忧** - 开发阶段支持 Python3 语法，构建时自动转换为 Python2
- 📦 **生态兼容** - 无缝对接 PyPI 生态，支持标准 `pyproject.toml` 配置
- 🚀 **智能构建** - 一键打包符合 MCStudio 规范的成品 Addons
- 🔥 **热重载开发** - 实时监控代码变更，支持 MCStudio 热更新

## 📖 为何选择此工具？

### 传统开发痛点
- 📜 **代码复用困难** - 通过 **文件拷贝** 导致版本管理混乱
- 🚧 **协作效率低下** - 多项目 **重复代码** 维护成本高
- ⚠️ **语法限制** - 中国版仅支持 Python2，缺乏现代语法支持

### mcpywrap 解决方案
1. **标准化开发**  
通过 `pyproject.toml` 声明项目元数据和依赖关系，实现真正的模块化开发

2. **现代开发体验**  
开发阶段使用 Python3 语法，构建时通过 3to2 自动转换，兼顾开发效率与运行兼容

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
mcpy init
```
交互式创建项目结构，自动生成标准的 Mod 框架。

## 🛠 工作流指南

### 依赖管理
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy`                 | 维护项目，将项目安装到系统 site-package 环境            |
| `mcpy add <package> [version]` | 添加指定版本依赖          |
| `mcpy remove <package>`        | 移除依赖               |

### 构建与开发
```bash
# 生产构建（输出到配置的 build 目录）
mcpy build

# 开发模式（热重载 + 实时构建）
mcpy dev
```

## 🤝 参与贡献
欢迎提交 Issue 和 PR！请先阅读 [贡献指南](CONTRIBUTING.md)。

## 开源协议
[MIT License](LICENSE) © 2025 EaseCation
