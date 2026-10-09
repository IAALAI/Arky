"""Cold resource requests must work without an external download executable."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from openbachelors.app import app
from openbachelors.bp import bp_assetbundle
from openbachelors.util import helper


@pytest.fixture
def no_aria(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError('aria2c')
    monkeypatch.setattr(helper.subprocess, 'run', missing)
    monkeypatch.setattr(helper, 'TMP_DIRPATH', str(tmp_path / 'tmp'))
    monkeypatch.setattr(bp_assetbundle, 'ASSET_DIRPATH', str(tmp_path / 'assets'))
    return tmp_path


def mock_cdn(monkeypatch, handler):
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs:
                        factory(*args, transport=httpx.MockTransport(handler), **kwargs))


def test_cold_manifest_download_without_aria_is_cached(monkeypatch, no_aria):
    version = '26-09-22-07-47-20_6c71fa'
    manifest = {'versionId': version, 'abInfos': [{'name': 'manifest.idx'}]}
    requests = []
    def cdn(request):
        requests.append(request.method)
        return httpx.Response(200, json=manifest)
    mock_cdn(monkeypatch, cdn)
    with TestClient(app) as client:
        url = f'/assetbundle/official/Android/assets/{version}/hot_update_list.json'
        for _ in range(2):
            response = client.get(url)
            assert response.status_code == 200
            assert response.json() == manifest
    assert requests == ['HEAD', 'GET']
    assert json.loads((no_aria / 'assets' / version / 'hot_update_list.json').read_text()) == manifest
    assert not list((no_aria / 'tmp').iterdir())


@pytest.mark.asyncio
async def test_failed_http_download_preserves_existing_file(monkeypatch, no_aria):
    mock_cdn(monkeypatch, lambda request: httpx.Response(404))
    target = no_aria / 'assets'
    target.mkdir()
    (target / 'manifest.json').write_bytes(b'previous-valid-file')
    with pytest.raises(httpx.HTTPStatusError):
        await helper.download_file('https://cdn/manifest.json', 'manifest.json', str(target))
    assert (target / 'manifest.json').read_bytes() == b'previous-valid-file'
    assert not list((no_aria / 'tmp').iterdir())


@pytest.mark.asyncio
async def test_interrupted_download_does_not_publish_partial_cache(monkeypatch, no_aria):
    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'partial-content'
            raise httpx.ReadError('connection interrupted')
    mock_cdn(monkeypatch, lambda request: httpx.Response(200, stream=Interrupted()))
    target = no_aria / 'assets'
    with pytest.raises(httpx.ReadError):
        await helper.download_file('https://cdn/manifest.json', 'manifest.json', str(target))
    assert not (target / 'manifest.json').exists()
    assert not list((no_aria / 'tmp').iterdir())
