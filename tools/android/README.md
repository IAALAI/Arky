# Android debugging

Use an unchanged official APK whose version matches `conf/version.json`.
The launcher checks the installed APK hash and the resource manifest before
starting the client. A modified native bootstrap is rejected.

```sh
cd tools/android
npm ci
npm run build
cd ../..
.venv/bin/python -m pip install -r tools/android/requirements.txt
.venv/bin/python scripts/android-client-debug.py \
  --serial 192.168.240.112:5555 \
  --backend http://127.0.0.1:18443 \
  --apk /path/to/original-2.7.71.apk
```

The selected device must already expose an authorized Frida endpoint. Waydroid
provides the project's existing debug server. Root access on a physical phone
is not performed automatically by these tools.

Game and account domains are supplied by DNS/hosts. The runtime Java adapter
changes HTTPS to HTTP only for those domains, to accommodate the local account
service; CDN URLs keep their original host and scheme. The managed hooks support
the local server's unsigned configuration responses and its debug certificate.
All changes are scoped to the running game process.

`ready` records identify successful Java and managed initialization; hook errors
are logged explicitly. Client/resource version mismatches and repacked APKs fail
preflight instead of being launched and silently failing resource initialization.

The device's installed package and resource files are not edited. Keep the
launcher running while the debug client is in use. Restart the client through
this launcher when reconnecting after a crash.
