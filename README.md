# Arky

明日方舟本地服务端，面向 ARM64 Linux / Waydroid 安卓客户端。当前发布版本：**2.7.71 v261009**，配套资源版本 `26-09-22-07-47-20_6c71fa`。

基于 [OpenBachelorS cbe89d7](https://github.com/pfyy/OpenBachelorS/tree/cbe89d7baff166fd339bebae19f19b9cebcfd580) 扩展。主要源码在 `src/openbachelors/`，部署配置在 `deploy/`，启动及旧 Java 存档迁移工具在 `scripts/`。

本次包含基建贸易、制造、加工、专精训练、心情与离线结算，以及第三、第六肉鸽主题的地图、事件、藏品、招募、战斗领奖和结束探索规则。基建和肉鸽新增业务采用协议、服务、领域规则、存档适配分层；完整玩法覆盖范围见实现文档。卫戍协议暂缓，不包含尚未完成的实验模块。

## 启动

使用 Python 3.12，在仓库根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.arm64.lock
./scripts/start-native.sh
```

服务以单个 worker 监听 `127.0.0.1:18443`。根据设备修改 `conf/config.json`；Waydroid 的域名映射、Nginx 80/443 入口及 systemd 部署见 [spark 部署说明](README.spark.md)。账号沿用本地信任模式，使用手机号标识存档。

## 验证与实现记录

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q
```

发布前在 spark ARM64 的独立稳定版本目录运行，87 项测试通过。Android 2.7.71 的真实客户端验证和剩余功能范围见：

- [基建实现与实机验证](BASE_IMPLEMENTATION.md)
- [肉鸽实现与实机验证](ROGUELIKE_IMPLEMENTATION.md)
- [Android ARM64 接入记录](doc/android-arm64.md)

`multi_sav/`、APK、资源包、调试日志、私钥和本地虚拟环境不随源码发布。上游版本与资源更新工作流改为手动触发，以保留当前验证过的客户端与资源配对。
