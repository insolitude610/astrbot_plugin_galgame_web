import pathlib
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


class _Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class _StarTools:
    @staticmethod
    def get_data_dir(_plugin_name):
        return pathlib.Path(tempfile.gettempdir()) / "galgame-security-tests"


class _Star:
    def __init__(self, context=None):
        self.context = context


class _Filter:
    def __getattr__(self, _name):
        def factory(*_args, **_kwargs):
            return lambda func: func

        return factory


astrbot = types.ModuleType("astrbot")
astrbot_api = types.ModuleType("astrbot.api")
astrbot_api.logger = _Logger()
astrbot_api_star = types.ModuleType("astrbot.api.star")
astrbot_api_star.StarTools = _StarTools
astrbot_api_star.Star = _Star
astrbot_api_star.Context = object
astrbot_api_event = types.ModuleType("astrbot.api.event")
astrbot_api_event.AstrMessageEvent = object
astrbot_api_event.MessageEventResult = object
astrbot_api_event.filter = _Filter()

astrbot_core = types.ModuleType("astrbot.core")
astrbot_platform = types.ModuleType("astrbot.core.platform")
astrbot_sources = types.ModuleType("astrbot.core.platform.sources")
astrbot_webchat = types.ModuleType("astrbot.core.platform.sources.webchat")
astrbot_webchat_queue = types.ModuleType(
    "astrbot.core.platform.sources.webchat.webchat_queue_mgr"
)
astrbot_webchat_queue.webchat_queue_mgr = object()
astrbot_utils = types.ModuleType("astrbot.core.utils")
astrbot_path = types.ModuleType("astrbot.core.utils.astrbot_path")
astrbot_path.get_astrbot_data_path = lambda: str(
    pathlib.Path(tempfile.gettempdir()) / "galgame-security-tests"
)
quart = types.ModuleType("quart")
quart.request = object()
quart.Response = type("Response", (), {})

sys.modules.setdefault("astrbot", astrbot)
sys.modules.setdefault("astrbot.api", astrbot_api)
sys.modules.setdefault("astrbot.api.star", astrbot_api_star)
sys.modules.setdefault("astrbot.api.event", astrbot_api_event)
sys.modules.setdefault("astrbot.core", astrbot_core)
sys.modules.setdefault("astrbot.core.platform", astrbot_platform)
sys.modules.setdefault("astrbot.core.platform.sources", astrbot_sources)
sys.modules.setdefault("astrbot.core.platform.sources.webchat", astrbot_webchat)
sys.modules.setdefault(
    "astrbot.core.platform.sources.webchat.webchat_queue_mgr", astrbot_webchat_queue
)
sys.modules.setdefault("astrbot.core.utils", astrbot_utils)
sys.modules.setdefault("astrbot.core.utils.astrbot_path", astrbot_path)
sys.modules.setdefault("quart", quart)
