# mcpywrap

mcpywrap 是一个用于将 《我的世界》中国版 的 ModSDK / 资源包 的包管理工具。
支持以 Addons 维度来管理依赖，并在构建时，自动打包到一个 MCStudio 项目中，从而进行正确测试和发布。

## 安装

```bash
pip install mcpywrap
```

## 使用方法

### 初始化项目

```bash
mcpywrap init
```

交互式初始化项目，创建基础的包信息，指定构建目标路径等。

### 添加依赖

```bash
mcpywrap add <name> [<version>]
```
添加依赖到项目中，支持指定版本号。

### 移除依赖

```bash
mcpywrap remove <name>
```
移除项目中的依赖。

### 构建项目

```bash
mcpywrap build
```

将 Python 3 项目转换为 Python 2 项目。

### 开发模式

```bash
mcpywrap dev
```

监控代码变化，自动执行构建。

### 发布到 PyPI

```bash
mcpywrap publish
```

将项目发布到 PyPI。

## 许可证

MIT
