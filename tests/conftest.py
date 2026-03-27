import sys
import types


def install_stub(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


install_stub("amcrest", AmcrestCamera=object)
install_stub("amcrest.exceptions", CommError=Exception)
install_stub("coloredlogs", install=lambda *_args, **_kwargs: None)
install_stub("hikvisionapi", AsyncClient=object)
install_stub("reolinkapi", Camera=object)
install_stub("pytapo", Tapo=object)
install_stub("uiprotect", ProtectApiClient=object)

aiomqtt = install_stub("aiomqtt", Client=object, Message=object)
aiomqtt_exceptions = install_stub("aiomqtt.exceptions", MqttError=Exception)
aiomqtt.exceptions = aiomqtt_exceptions
asyncio_mqtt = install_stub("asyncio_mqtt", Client=object)
asyncio_mqtt_error = install_stub("asyncio_mqtt.error", MqttError=Exception)
asyncio_mqtt.error = asyncio_mqtt_error


def _backoff_decorator(*_args, **_kwargs):
    def decorator(fn):
        return fn

    return decorator


install_stub("backoff", on_predicate=_backoff_decorator, expo=lambda *_args, **_kwargs: None)
