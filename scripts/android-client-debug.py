#!/usr/bin/env python3
"""Launch an unchanged Android APK with observable, app-scoped debug hooks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import threading
import urllib.request


PACKAGE = 'com.hypergryph.arknights'
ROOT = Path(__file__).resolve().parents[1]


def adb(serial, *args):
    return subprocess.check_output(['adb', '-s', serial, *args], text=True).strip()


def check_version(actual, expected):
    if actual != expected:
        raise ValueError(f'Android APK {actual} does not match server clientVersion {expected}')


def check_apk(serial, apk):
    package_path = adb(serial, 'shell', 'pm', 'path', PACKAGE)
    paths = [line.removeprefix('package:') for line in package_path.splitlines()]
    if len(paths) != 1:
        raise ValueError('Expected the original standalone APK, not split packages')
    with apk.open('rb') as original:
        digest = hashlib.file_digest(original, 'sha256').hexdigest()
    installed = adb(serial, 'shell', 'sha256sum', paths[0]).split()[0]
    if installed != digest:
        raise ValueError('Installed APK differs from the supplied original; restore it before debugging')


def preflight(serial, backend, apk=None):
    with urllib.request.urlopen(backend.rstrip('/') + '/config/prod/official/Android/version', timeout=15) as response:
        version = json.load(response)
    package = adb(serial, 'shell', 'dumpsys', 'package', PACKAGE)
    match = re.search(r'\bversionName=(\S+)', package)
    if match is None:
        raise ValueError('Android game is not installed')
    check_version(match[1], version['clientVersion'])
    if apk is not None:
        check_apk(serial, apk)
    manifest_url = (backend.rstrip('/') + '/assetbundle/official/Android/assets/'
                    + version['resVersion'] + '/hot_update_list.json')
    with urllib.request.urlopen(manifest_url, timeout=30) as response:
        manifest = json.load(response)
    if manifest.get('versionId') != version['resVersion'] or not manifest.get('abInfos'):
        raise ValueError('Resource manifest does not match the selected server resource version')
    print('Preflight:', version['clientVersion'], version['resVersion'], 'manifest OK', flush=True)
    return version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', required=True)
    parser.add_argument('--backend', default='http://127.0.0.1:18443')
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'tools/android/hooks.bundle.js')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    preflight(args.serial, args.backend, args.apk)
    if args.check_only:
        return
    if not args.bundle.is_file():
        parser.error('Build tools/android/hooks.bundle.js with npm ci && npm run build')
    import frida
    device = frida.get_device(args.serial, timeout=10)
    adb(args.serial, 'shell', 'am', 'force-stop', PACKAGE)
    pid = device.spawn(PACKAGE)
    session = device.attach(pid)
    finished = threading.Event()
    ready = threading.Event()
    initialized = set()
    script = session.create_script(args.bundle.read_text())

    def on_message(message, data):
        print(json.dumps(message, ensure_ascii=False), flush=True)
        payload = message.get('payload', {})
        if payload.get('type') == 'ready':
            initialized.add(payload['scope'])
            if initialized >= {'java', 'managed'}:
                ready.set()
        elif message.get('type') == 'error' or payload.get('type') == 'hook-error':
            finished.set()

    script.on('message', on_message)
    session.on('detached', lambda *unused: finished.set())
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *unused: finished.set())
    script.load()
    device.resume(pid)
    print('Debug process:', pid, 'APK unchanged; waiting for hook readiness', flush=True)
    try:
        for _ in range(30):
            if ready.wait(1) or finished.is_set():
                break
        if not ready.is_set():
            adb(args.serial, 'shell', 'am', 'force-stop', PACKAGE)
            raise RuntimeError('Debug initialization failed; client stopped before continuing with partial hooks')
        print('Java and managed hooks ready', flush=True)
        finished.wait()
    finally:
        adb(args.serial, 'shell', 'am', 'force-stop', PACKAGE)
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass


if __name__ == '__main__':
    main()
