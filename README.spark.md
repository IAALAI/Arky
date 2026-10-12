# spark 上的安卓主服务

主入口：`~/player/Ark/server`。真实源码在 `newVersion/native`。
当前目标客户端 Android 2.7.71（ARM64），资源 26-09-22-07-47-20_6c71fa。
源码发布版本：`2.7.71 v261009`，仓库 [IAALAI/Arky](https://github.com/IAALAI/Arky)。

```sh
cd ~/player/Ark/server
./scripts/service.sh status
./scripts/service.sh restart
./scripts/service.sh logs
./scripts/client-start.sh
```

客户端接入需要 `tools/android` 的可重建调试层。首次运行先按
[Android 调试说明](tools/android/README.md) 构建 bundle 并安装调试依赖。
启动器核对原始 APK、客户端版本和资源清单；客户端和资源应保持 2.7.71 配对。
资源下载优先使用 aria2；精简部署缺少 `aria2c` 时改用 Python 流式下载，完成后才写入缓存。

- `arknights.service`：以 iaalai 运行一个 Uvicorn worker，监听 127.0.0.1:18443。
- Nginx：以原有受信任证书接入 80/443，仅放行本机和 Waydroid 网段。
- `client/hosts`：游戏与账号域名映射到 Waydroid 网关 192.168.240.1，CDN 保持原地址。
- 客户端在 `wayland-arka` Weston 调试会话运行，1280×720。ADB 可截图、点击及获取日志。
- 该显示会话使用 headless 后端，因此正常运行也不会自动在 GNOME 桌面出现窗口。启动脚本通过用户服务保持新会话运行，避免 SSH 退出时停止；容器重启后也会重新启动既有的 Waydroid Frida helper。
- 不需要 Windows 程序、Wine 或其他指令集兼容层。

在 spark 的图形桌面终端查看和操作实时画面：

```sh
cd ~/player/Ark/newVersion/release-v261009
/usr/bin/python3 scripts/waydroid-view.py
```

窗口标题为“Arky - Waydroid 实时画面”。使用系统 Python 的 GTK 3 / GdkPixbuf 支持和 ADB 读取新画面，适用于此镜像没有可用 AVC 视频编码器、scrcpy 无法投屏的情况。刷新率较低，鼠标支持点击和拖动；关闭窗口不停止游戏。状态栏显示最新帧的北京时间，断线时明确提示显示的是旧画面。它默认只连接 Waydroid 的 `192.168.240.112:5555`。

帐号为本地信任模式，手机号作为保存标识。已迁移旧端两个已初始化账号。
新账号沿用上游解锁模板。原 Java 密码认证尚未接回，不能把该服务开放到公网。
旧客户端缓存会话通过 SHA-256 别名映射回导入账号；别名保存在忽略的 multi_sav/session_aliases.json。
迁移后须运行 scripts/link_java_sessions.py SOURCE --apply 并重启服务。

存档在 `multi_sav/`，调试记录和 APK 在忽略的 `test/client/`。
旧客户端应用数据备份在 `test/client/backup/app-data/`。
旧端和所有 Git 改动完整保存在 `~/player/Ark/archive/2026-10-05-before-native/`。
不要删除归档，旧证书及 APK 可用于回退。

基建已补充贸易、制造、加工、专精训练、心情及离线结算；第三、第六肉鸽主题已加入本地地图、事件、藏品和结算规则。
详细实现和边界见 [基建记录](BASE_IMPLEMENTATION.md)、[肉鸽记录](ROGUELIKE_IMPLEMENTATION.md)及 [ARM 接入记录](doc/android-arm64.md)。卫戍协议暂缓。
已通过真实客户端第六主题“猎犬病原”实战、结算和重启恢复；制造站进驻及生产倒计时也已验证。
实机验收报告在 spark 的 `../reports/WAYDROID.md`，截图在忽略的 `test/client/`；本次稳定版本发布前 87 项回归用例通过。

部署配置的可审查副本在 `deploy/`，不含私钥。
日志：`journalctl -u arknights.service`；
HTTP 路径和状态：`/var/log/nginx/arknights-access.log`（不记录查询参数）。
