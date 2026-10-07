# coding: utf-8
"""可选临时客户端观测探针；不装入 Addon，不计数脚本或模拟 tick。"""
import sys
import time
import types

_api = mcpy.api
_base = _api.GetClientSystemCls()
_module_name = '_mcpy_optional_key_timeline_probe'
_module = sys.modules.get(_module_name)
if _module is None:
    _module = types.ModuleType(_module_name)
    sys.modules[_module_name] = _module


class KeyProbe(_base):
    def __init__(self, namespace, name):
        _base.__init__(self, namespace, name)
        self.api = _api
        self.player = mcpy.player
        source = self.player.capabilities()['timeline']['clock_source']
        self.clock = time.monotonic if source == 'time.monotonic' else time.clock
        self.timer = None
        self.operation = None
        self.samples, self.keys, self.errors = [], [], []
        self.truncated = False
        self.listening = True
        self.ListenForEvent(self.api.GetEngineNamespace(), self.api.GetEngineSystemName(),
                            'OnKeyPressInGame', self, self.on_key)

    def on_key(self, args):
        if self.operation is not None:
            if len(self.keys) < 512:
                self.keys.append({'time': self.clock(), 'args': dict(args)})
            else:
                self.truncated = True

    def sample(self):
        if self.operation is None:
            return
        if self.clock() > self.deadline or len(self.samples) >= 512:
            self.truncated = True
            self.stop()
            return
        try:
            factory = self.api.GetEngineCompFactory()
            pid = self.api.GetLocalPlayerId()
            try:
                status = self.player.status(self.operation)
                operation = {k: status.get(k) for k in ('index', 'state', 'held_keys', 'started_at')}
            except ValueError:
                operation = None
            self.samples.append({'time': self.clock(), 'position': factory.CreatePos(pid).GetFootPos(),
                                 'input_vector': factory.CreateActorMotion(pid).GetInputVector(),
                                 'operation': operation})
        except Exception as error:
            if len(self.errors) < 10:
                self.errors.append(str(error))

    def start(self, operation):
        self.stop()
        self.operation = operation
        self.samples, self.keys, self.errors = [], [], []
        self.truncated = False
        self.deadline = self.clock()+15.
        self.timer = self.api.GetEngineCompFactory().CreateGame(self.api.GetLevelId()).AddRepeatedTimer(.02, self.sample)
        if self.timer is None:
            self.operation = None
            raise ValueError('Cannot start bounded observation timer')
        return {'ok': True}

    def stop(self):
        if self.timer is not None:
            self.api.GetEngineCompFactory().CreateGame(self.api.GetLevelId()).CancelTimer(self.timer)
            self.timer = None
        self.operation = None
        return {'ok': True, 'samples': list(self.samples), 'keys': list(self.keys),
                'errors': list(self.errors), 'truncated': self.truncated}

    def close(self):
        result = self.stop()
        if self.listening:
            self.UnListenForEvent(self.api.GetEngineNamespace(), self.api.GetEngineSystemName(),
                                  'OnKeyPressInGame', self, self.on_key)
            self.listening = False
        return result


_previous = getattr(_module, 'probe', None)
if _previous is not None:
    _previous.close()
    # 注册系统仍持有类及其 globals；只替换其观测方法依赖，不回收模块。
    _previous.player = mcpy.player
    _previous.listening = True
    _previous.ListenForEvent(_api.GetEngineNamespace(), _api.GetEngineSystemName(),
                             'OnKeyPressInGame', _previous, _previous.on_key)
    _probe = _previous
else:
    _module.KeyProbe = KeyProbe
    _probe = _api.RegisterSystem('mcpy_optional_key_timeline', 'probe', _module_name+'.KeyProbe')
    _module.probe = _probe
if _probe is None:
    raise ValueError('Cannot register optional key timeline observation probe')
_result = {'ok': True}
