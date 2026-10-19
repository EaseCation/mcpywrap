# QuMod 接入

添加、恢复、升级和移除 QuMod 的公开用法统一维护在 [Skill 依赖与 QuMod](../skills/mcpywrap/references/project-dependencies.md)。

QuMod 是通用 Git 依赖的预设：来源、推荐提交、目录和模板由 `framework_presets` 维护，标准缓存、解析与组装层不识别框架名称。命令返回实际锁定提交；源码版本字段不表示存在同名官方 Release，已有项目不会随工具升级自动更换依赖版本。

运行库安装到各自 Mod 的脚本目录，系统名和通信通道保持各自作用域。工具不自动合并 Optional、不按业务 import 裁剪代码，也不运行上游 EXE。其他框架使用相同的[Git 依赖契约](git-dependencies.md)。
