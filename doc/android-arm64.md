# Android ARM64 接入记录

工作目录：/home/iaalai/player/Ark/newVersion/native
目标设备：spark，aarch64，CPython 3.12 原生运行。未安装 Wine、Box64 或其他兼容层。

## 基线与版本

源码固定于 OpenBachelorS 提交 cbe89d7baff166fd339bebae19f19b9cebcfd580：
https://github.com/pfyy/OpenBachelorS/tree/cbe89d7baff166fd339bebae19f19b9cebcfd580

Android 客户端目标 2.7.71，资源版本 26-09-22-07-47-20_6c71fa，funcVer V070。
这表示已核实的社区源码版本，不表示已核实官方当天最新版本。
Windows 社区包的 Nuitka EXE 仅用于资料对照，没有作为 ARM 服务运行。
未发布或推送该源码副本；上游快照未发现 LICENSE 文件，发布前需确认授权。

## 2026-10-05 Waydroid 接入

当前唯一入口为 `/home/iaalai/player/Ark/server`（链接到本源码）。
旧 Arka、Arka_s、LocalArknights、target 和第一阶段 Java 副本已完整移入
`/home/iaalai/player/Ark/archive/2026-10-05-before-native/`，包括 Git 历史及未提交改动。

`arknights.service` 管理单 worker 后端，Nginx 使用原有受信任证书监听 80/443，
仅允许本机和 Waydroid 网段访问。后端仍在 127.0.0.1:18443。
客户端已原位升级至 2.7.71 ARM64；已在客户端完成旧账号登录、制造站进驻/计时以及第六主题实战结算。
截图在 test/client/，完整记录在 ../reports/WAYDROID.md。

```sh
cd /home/iaalai/player/Ark/server
./scripts/service.sh status
./scripts/service.sh restart
./scripts/client-start.sh
```

`scripts/candidate.py` 检测到已安装的 systemd 单元后会转交 systemctl，防止启动第二个存档 worker。

## 初始候选的启停（历史）

在本目录执行：

```sh
.venv/bin/python scripts/candidate.py start
.venv/bin/python scripts/candidate.py status
.venv/bin/python scripts/candidate.py restart
.venv/bin/python scripts/candidate.py stop
```

候选服务监听 http://127.0.0.1:18443，只有一个 worker。
这是 HTTP 端口；18443 的编号不意味着配置了 TLS。
日志和 PID 位于 ../reports/。scripts/start-native.sh 可用于前台运行。
第一阶段未注册开机服务；现已由上面的 systemd + Nginx 方案接管。

本候选沿用上游的本地账号信任模式，手机号标识即 token，并非原 Java 密码认证。
后端绑定回环地址，Nginx 对本机和 Waydroid 网段开放。TLS/客户端入口已接入；账号仍为本地信任模式。
资源请求按上游配置重定向到资源 CDN，已在 Waydroid 内完成约 3.7 GB 新资源下载。

## 本次实现

- 接入上游六个肉鸽主题的沙盒流程，包括 rogue_6 的 gridZone 路由。
- 旧账号同步时只补缺失的肉鸽主题元数据，保留已有主题进度和当前局。
- 招募按 charId 匹配玩家拥有的干员，兼容 Java 连续实例编号，不再假设实例号等于干员编号。
- 基建进驻、跨房间换班、助理配置增加拥有权、人数、重复 ID、房间状态校验；缺失或错误的干员基建对象按本人重建。
- 制造站支持基础速率生产、队列、容量、材料扣除和领取；无效请求不提交修改，重复领取不重复发放。
- 同账号请求在一个 worker 内串行读改存；JSON 临时文件写入后原子替换。
- 修复删除兄弟节点与嵌套更新同时发生时，上游保存层残留删除标记的问题。
- 提供默认只预览、备份后应用、拒绝覆盖现有账号的 Java 存档导入脚本。
- 修复反向代理无端口域名生成 :None 地址、旧缓存登录误建测试档、字典子树替换混入模板干员，以及制造站客户端显示暂停的问题。

文件存档的原子性以单个文件为单位；多个文件没有跨文件事务。
不要增加 worker 数量，跨进程锁尚未实现。

## 验证

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q test/test_session.py test/test_origin.py test/test_android_smoke.py test/test_import_java.py test/test_player_data.py test/test_helper.py test/test_manufacture.py test/test_save_safety.py
.venv/bin/python test/live_smoke.py /home/iaalai/player/Ark/archive/2026-10-05-before-native/target/data/account.json
```

离线/ASGI 用例 47 项通过。包含六个主题的开局、商店招募、战斗协议推进、结算与放弃，以及制造、进驻、无效请求回滚、存档并发和迁移校验。
live_smoke 会重启这个独立候选服务，用一个临时旧账号副本验证真实 TCP、旧编号招募、基建操作和重启存档恢复，最后清除自己的副本。
独立于以上协议检查，本次已在 Android 客户端完成第六主题开局、商店招募、能天使部署、“猎犬病原”成功通过、结算返回地图和重启恢复。仍为上游沙盒规则，不能代表完整玩法已实现。
制造站已验证白雪进驻、基础作战记录生产队列与倒计时；未等待生产完成后的真实领取，领取行为由自动化用例验证。

## 存档迁移

```sh
.venv/bin/python scripts/import_java_save.py /home/iaalai/player/Ark/archive/2026-10-05-before-native/target/data/account.json
# 确定目标目录没有这些账号，并停止候选服务后，才使用 --apply。
```

首次应用已复制 2 个已初始化账号，跳过 2 个未初始化账号。
源文件未修改。备份位于 test/migration-backups/，报告位于 ../reports/migration-apply.json。
原密码和 Java 邮件表不导入；封禁账号跳过；候选账号使用相同手机号标识。
第二阶段新增 link_java_sessions.py，用旧 secret 的 SHA-256 建立缓存登录别名；不在映射文件保存原始 secret。
这样保留登录态的旧客户端会进入自己的迁移存档，不会误建默认全解锁测试档。
不要将 multi_sav/、备份或测试产生的存档提交到 Git。

## 尚未完成

- 肉鸽仍是上游沙盒：固定开放地图、资源和商店规则简化，不能视为 Windows 社区版完整随机探索。
- GM 工具与 Windows 编译版的扩展肉鸽模块、月度小队、深入调查等尚未逐项移植。
- 基建干员技能加成、心情消耗/恢复、无人机、自动补单、阶段条件配方尚未实现；贸易、加工、训练、线索等也尚未补齐。
- 新账号沿用上游测试模板，默认解锁很多内容；正式进度模式需要另行设计模板和权限。
- 旧存档只完成数据保留和关键路径兼容验证，其他模块仍需逐项验证。
- 已完成 2.7.71 APK、TLS、资源下载及关键游戏路径验收；其余玩法仍需逐项验证。
