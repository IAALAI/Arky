from starlette.requests import Request
from openbachelors.util.server_url import get_server_url
import pytest

@pytest.mark.parametrize("scheme,host,expected", [
    ("http", b"ak-conf.hypergryph.com", "http://ak-conf.hypergryph.com"),
    ("https", b"ak-conf.hypergryph.com", "https://ak-conf.hypergryph.com"),
    ("http", b"127.0.0.1:18443", "http://127.0.0.1:18443"),
])
def test_client_origin(scheme, host, expected):
    request = Request({"type": "http", "scheme": scheme, "path": "/config/prod/official/network_config", "root_path": "", "query_string": b"", "headers": [(b"host", host)]})
    assert get_server_url(request) == expected
