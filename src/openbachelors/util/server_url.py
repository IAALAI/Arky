from ..const.filepath import CONFIG_JSON, VERSION_JSON
from .const_json_loader import const_json_loader


def get_server_url(request=None):
    if const_json_loader[CONFIG_JSON]["adaptive"] and request is not None:
        url = str(request.base_url).rstrip("/")
    else:
        host = const_json_loader[CONFIG_JSON]["host"]
        port = const_json_loader[CONFIG_JSON]["port"]
        url = f"http://{host}:{port}"
    return url
