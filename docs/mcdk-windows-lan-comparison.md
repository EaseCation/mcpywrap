# MCDK 同引擎本地主客机实测

日期：2026-10-16。实验目录：`test/mcdk-lan-20261016`（忽略目录，保留日志、启动脚本与世界）。

## 环境与判定方式

- 两端固定同一 `D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.420447/Minecraft.Windows.exe`。
- MCDK 使用上游 v1.6.1 发布的未修改 `mcdk.exe`，SHA-256 为
  `2CD4348C05A1B3855F4397526A9C4C3DEEA359D2E57F07A61E2669BD5B47349B`。
- 首组主机/Sub 共用隔离的 `shared-profile`，通过子进程环境同时指定 USERPROFILE、APPDATA、LOCALAPPDATA，已核验 Windows known-folder 查询结果。它保留 MCDK 原来的共享语义，未改成每成员独立资料。
- 仅继承画面和输入偏好。MCDK 清理与挂载发生在这个隔离数据根，不使用用户全局包目录。
- 独立 MCP 端口用于尝试观察，不改变游戏联机协议。MCDK 的 Debug Mod IPC 本轮未连接成功，因此没有把 MCP 启动或 HUD 当作双玩家成功。
- 游戏菜单选择带“局域网世界”标记的测试世界卡片；没有点击同名本地存档，也没有连接列表中发现的其他服务器。

## 实验 A：原始 MCDK 主机 + Sub

主机 MCDK PID 141472，游戏 PID 144308；Sub MCDK PID 144888，游戏 PID 147856。完整配置及 MCDK 启动身份保存在 `host/launch.json`、`sub/launch.json`。

主机配置由 MCDK 生成，仅含 world_info.level_id、空 room_info、player_info 与 skin_info。Sub 使用 `MCDEV_IS_SUBPROCESS_MODE=1`、`MCDEV_AUTO_JOIN_GAME=0`，不传 cppconfig。

实际操作：

1. 等待主机进入超平坦世界 `MCDK LAN 20261016`。
2. Sub 在主菜单选择“开始游戏”。世界列表出现“局域网世界 / MCDK LAN 20261016 / MCDK_Host 的世界 / 1/10”。
3. 选择该局域网卡片，在“线上游戏未分级”提示中选择“继续”。
4. 客机进入连接流程，随后弹出 BinaryStream 断言并退出；主机仍运行，暂停菜单仅有 MCDK_Host 一人。

游戏日志提供了比“两个窗口”更明确的阶段证据：

| 时间 | 端侧 | 证据 |
| --- | --- | --- |
| 10:52:32 | 主机 | `Player connected: MCDK_Host` |
| 10:53:53 | 主机 | `Player Spawned: MCDK_Host` |
| 10:59:12.085 | 主机 | `onNewIncomingConnection for nethernet:17622819534386129589` |
| 10:59:12.109 | 客机 | `onConnect, server id: nethernet:15977134646586825201, local id: nethernet:17622819534386129589` |
| 10:59:12.126 | 客机 | `corrupted data incoming` |
| 10:59:12.144 | 客机 | `String length value 7523 is larger than available data bytes 17. Previous read ptr: 3`，`BinaryStream.cpp:408` |

原始日志分别为隔离资料目录下 `logs/Debug_Log2026-10-16_10-50-28.txt` 和 `logs/Debug_Log2026-10-16_10-54-39.txt`。

**结果：局域网发现及 NetherNet 连接已完成，第二玩家进入世界失败。** 不能写成“MCDK 已成功联机”，也不能写成“无法发现端口所以无法联机”。数据格式不一致、游戏模式初始化或引擎回归均需要进一步对照；此断言不能单独证明身份冲突、加密开关或某个 cppconfig 字段就是根因。

## 与 mcpywrap 的已知差异

| 项目 | MCDK 原始流程 | 当前 mcpywrap 流程 |
| --- | --- | --- |
| 主机配置 | 最小 cppconfig，先生成 level.dat 和标准世界包引用 | 完整世界/包/room_info 配置，统一部署后启动 |
| 客机启动 | 不带 cppconfig，进入游戏菜单 | 本地组先发现 ServerTarget，再调用网络会话启动 |
| 加入动作 | 点击游戏发现的局域网房间，由引擎执行 NetherNet 连接 | local_endpoint 仅处理端口查询/RakNet；network 配置使用 multiplayer_game_type=100 |
| 已验证的外服流程 | 本轮未测试 | 此前双客户端连接隔离外服成功，不能代替本地主客机验收 |

两种测试世界的 `MultiplayerGame`、`MultiplayerGameIntent`、`LANBroadcast`、`LANBroadcastIntent` 读取值均为 1（`world-network-flags.json`）。因此不能把差异简单归结为存档未开启联机。

一次预备对照中，Sub 比 mcpywrap 游戏进程先启动：Sub 持有 UDP 7551，主机没有该监听，列表未发现主机。这次记录只用于指出启动顺序干扰，不用于下配置根因结论；正式对照必须等主机就绪后才启动 Sub。7551 是本轮观测到的发现端口，不能拿来替代游戏服务器地址。

## 实验 B：mcpywrap 主机 + 共享资料的 MCDK Sub

主机先完成世界加载，再启动 Sub。主机会话 `043623fd0feb43609a2c48e05f94e52c`，游戏 PID 149992；Sub 游戏 PID 146572。

- 主机持有 IPv4/IPv6 UDP 7551（`mcpy-host/ordered-host-ports.json`）。
- Sub 从游戏列表发现 `MCPY LAN Compare / mcpy_043623fd 的世界 / 1/10`。
- 11:22:18 主机记录 NetherNet 新连接与 `Login to the Server`。
- Sub 画面显示“你可能已在其他地点登录。无法连接”。
- 随后通过主机公开 `runtime py` 查询，仍只有 `mcpy_043623fd` 一个玩家；本地世界 ID 与原世界相同，端口查询仍返回 -1。证据为 `mcpy-host/host-after-shared-sub.json`。

这次结果表明 mcpywrap 的主机也能被游戏自身的局域网入口发现，并接受 NetherNet 连接。共享身份是此拒绝的直接排查方向，但尚不能仅凭错误文案断言哪个身份文件起决定作用。

## 实验 C：保留同一主机，只给 Sub 独立资料目录（成功）

主机会话、世界、引擎均保持实验 B 的值不变；客机仍是原版 MCDK Sub，不带 cppconfig。只将客机 USERPROFILE、APPDATA、LOCALAPPDATA 指向 `guest-profile`，验证系统目录解析后启动。客机 MCDK PID 138308，游戏 PID 146872。

`identity-comparison.json` 记录两端生成的 `deviceid.txt`、`minecraftpe/clientId.txt` 摘要不同。这里验证了整套资料隔离有效，没有进一步拆分哪个身份文件单独足够。

成功的游戏内操作路径：

1. 新资料首次菜单选“更多选项”，进入正常菜单后选“开始游戏”（首屏“开始”会进入创建世界引导）。
2. 点击带“局域网世界”标记的 `MCPY LAN Compare / mcpy_043623fd 的世界 / 1/10`。
3. 确认线上游戏提示，选择下载测试资源包并加入。
4. 等待世界加载完成。客机显示 Steve，暂停菜单同时列出 Steve 和 mcpy_043623fd。

验证证据：

- 11:28:00 主机原生日志记录 `Player connected: Steve`，11:28:29 记录 `Player Spawned: Steve`。
- `mcpy-host/server-two-players.json`：主机服务端确认两名玩家，ID 分别为 `-4294967295` 与 `-8589934522`。
- `mcpy-host/host-after-isolated-sub.json`：主机客户端也看到这两名玩家，本地世界 ID 仍为 `3958fae2-dcdc-46bd-85ef-5dfeac45f65d`。
- 在服务端将 Steve 放置到 `(0.5, -60, -4.5)`；主机服务端和客户端随后读到相同的玩家位置 `(0.5, -58.37998962402344, -4.5)`（眼高与放置坐标差异不是不同世界）。客机画面同步离开重叠出生点，清楚看到前方主机及名称。证据为 `guest-position-request.json`、`server-after-guest-move.json`、`host-after-guest-move.json` 及 `guest-sees-host.jpg`。
- 单次键盘 W 输入没有产生可测位移，不能将它计为移动成功；本轮同步证据来自上述服务端位置变更和客机可见效果。
- `guest-two-players.jpg` 保存客机暂停菜单的双玩家名单。
- 客机资源位于自己的 `MinecraftPE_Netease/packcache`：两个缓存 manifest UUID 与主机当前行为包、资源包一致。它没有读取主机的 assembled 目录。测试包只有最小 manifest；本轮没有验证业务脚本加载、客机 Python 通道或协调热更。

**结果：同一 Windows 引擎下，mcpywrap 本地主机 + 独立资料 MCDK Sub 已通过游戏自身入口完成双玩家入场和位置同步。** 这是实机可行性闭环，尚不等于公开 `run --clients 2` 的自动流程已修通。实验 A 的原始 MCDK 主机解析断言未单独复测，不能将实验 C 的成功改写为 A 也成功。

### 退出阶段另外发现的问题

客机正常回到主菜单并关闭。主机点击“保存并退出”回到主菜单时出现 `Unknown texture format: 0` 断言，位置为 `ImageDescription.cpp:72`。这发生在双玩家和位置同步验收之后；没有证明它由联机或新部署引入，也不能忽略它并宣称退出/保存验收已通过。随后使用公开 `stop --session` 清理本任务主机，保留世界、日志与配置；不以进程结束作为保存保证。

## 对实现方向的约束

1. 游戏内局域网发现可以提供主机的 NetherNet 标识；“没有 RakNet pong”不等于主机不能联网。
2. 局域网加入不能在未验证的情况下复用第三方网络服 `ip/port/type=100` 配置；需要明确区分目标的连接方式。
3. 必须保留“发现房间 → 连接建立 → 玩家进入 → 同步验证”的阶段，不把前两项报告为联调成功。
4. 先核验原始 MCDK 和 mcpywrap 在同引擎的真实结果，再决定自动化接口；不通过关闭断言或放宽 ready 校验制造成功。
5. 保留已经验证有效的独立资料与稳定玩家身份。下一步应接入游戏的 NetherNet 发现/加入路径，而不是继续把广播端口送入第三方网络服连接配置。
6. 客机资源热更需要管理实际下载缓存与版本；不能仅比较主机部署目录就宣称已同步到客机。
7. 将退出阶段的纹理断言加入后续同引擎单客户端对照；先区分既有引擎/资源问题与联机引入的副作用。
