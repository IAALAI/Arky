"""Reject incompatible Android versions before launching the game."""
import importlib.util
import io
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    'android_client_debug', Path(__file__).parents[1] / 'scripts/android-client-debug.py')
debug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(debug)


def backend(monkeypatch, manifest_version='26-09-22-07-47-20_6c71fa'):
    replies = [
        {'clientVersion': '2.7.71', 'resVersion': '26-09-22-07-47-20_6c71fa'},
        {'versionId': manifest_version, 'abInfos': [{'name': 'manifest.idx'}]},
    ]
    monkeypatch.setattr(debug.urllib.request, 'urlopen',
                        lambda *args, **kwargs: io.BytesIO(json.dumps(replies.pop(0)).encode()))


def test_preflight_blocks_old_client_before_resource_fetch(monkeypatch):
    backend(monkeypatch)
    monkeypatch.setattr(debug, 'adb', lambda *args: 'versionName=2.7.21')
    with pytest.raises(ValueError, match='does not match'):
        debug.preflight('device', 'http://backend')


def test_preflight_rejects_mismatched_resource_manifest(monkeypatch):
    backend(monkeypatch, manifest_version='26-04-22-10-22-20_1d417a')
    monkeypatch.setattr(debug, 'adb', lambda *args: 'versionName=2.7.71')
    with pytest.raises(ValueError, match='manifest does not match'):
        debug.preflight('device', 'http://backend')


def test_repacked_apk_is_blocked_even_when_version_matches(monkeypatch, tmp_path):
    apk = tmp_path / 'original.apk'
    apk.write_bytes(b'official-byte-stream')
    monkeypatch.setattr(debug, 'adb', lambda serial, *args:
                        'package:/data/app/base.apk' if args[1] == 'pm' else '0' * 64 + '  /data/app/base.apk')
    with pytest.raises(ValueError, match='differs from the supplied original'):
        debug.check_apk('device', apk)
