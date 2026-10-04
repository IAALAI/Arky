# spark 上的安卓主服务

主入口：`~/player/Ark/server`。真实源码在 `newVersion/native`。
当前目标客户端 Android 2.7.71（ARM64），资源 26-09-22-07-47-20_6c71fa。

```sh
cd ~/player/Ark/server
./scripts/service.sh status
./scripts/service.sh restart
./scripts/service.sh logs
./scripts/client-start.sh
```

- `arknights.service`：以 iaalai 运行一个 Uvicorn worker，监听 127.0.0.1:18443。
- Nginx：以原有受信任证书接入 80/443，仅放行本机和 Waydroid 网段。
- `client/hosts`：游戏与账号域名映射到 Waydroid 网关 192.168.240.1，CDN 保持原地址。
- 客户端在 `wayland-arka` Weston 调试会话运行，1280×720。ADB 可截图、点击及获取日志。
- 不需要 Windows 程序、Wine 或其他指令集兼容层。

帐号为本地信任模式，手机号作为保存标识。已迁移旧端两个已初始化账号。
新账号沿用上游解锁模板。原 Java 密码认证尚未接回，不能把该服务开放到公网。
旧客户端缓存会话通过 SHA-256 别名映射回导入账号；别名保存在忽略的 multi_sav/session_aliases.json。
迁移后须运行 scripts/link_java_sessions.py SOURCE --apply 并重启服务。

存档在 `multi_sav/`，调试记录和 APK 在忽略的 `test/client/`。
旧客户端应用数据备份在 `test/client/backup/app-data/`。
旧端和所有 Git 改动完整保存在 `~/player/Ark/archive/2026-10-05-before-native/`。
不要删除归档，旧证书及 APK 可用于回退。

肉鸽仍是沙盒规则；基建目前支持进驻、助理和基础制造，其余规则尚未齐全。
详细实现和边界见 [ARM 接入记录](doc/android-arm64.md)。
已通过真实客户端第六主题“猎犬病原”实战、结算和重启恢复；制造站进驻及生产倒计时也已验证。
验收报告在 `../reports/WAYDROID.md`，截图在忽略的 `test/client/`；47 项回归用例通过。

部署配置的可审查副本在 `deploy/`，不含私钥。
日志：`journalctl -u arknights.service`；
HTTP 路径和状态：`/var/log/nginx/arknights-access.log`（不记录查询参数）。
