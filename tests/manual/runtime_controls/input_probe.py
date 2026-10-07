# coding: utf-8
"""可选统一输入实机观测，不进入默认测试、业务包或正常启动。"""
import sys
import types
import mod.client.extraClientApi as api

_module_name = '_mcpy_optional_unified_input_probe'
_controller = mcpy.input
_player = mcpy.player


class Probe(api.GetClientSystemCls()):
    def __init__(self, namespace, name):
        api.GetClientSystemCls().__init__(self, namespace, name)
        self.operation = None
        self.samples, self.keys = [], []
        self.truncated = False
        self.timer = None
        self.ListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(), 'OnKeyPressInGame', self, self.key)

    def key(self, args):
        if self.operation is not None:
            if len(self.keys) < 512:
                self.keys.append(dict(args))
            else: self.truncated = True

    def sample(self):
        if len(self.samples) >= 512 or _controller.adapter.clock() > self.deadline:
            self.truncated = True
            self.stop()
            return
        state = _player._read()
        try: operation = _controller.status(self.operation)
        except ValueError: operation = {}
        self.samples.append({'position': state['position'], 'input_vector': state['input_vector'],
                             'held_keys': operation.get('held_keys', []), 'state': operation.get('state')})

    def start(self, operation):
        self.stop()
        self.samples, self.keys = [], []
        self.truncated = False
        self.operation = operation
        self.deadline = _controller.adapter.clock()+15
        self.timer = api.GetEngineCompFactory().CreateGame(api.GetLevelId()).AddRepeatedTimer(.02, self.sample)
        if self.timer is None: raise ValueError('No observation timer')
        return {'ok': True}

    def stop(self):
        if self.timer is not None:
            api.GetEngineCompFactory().CreateGame(api.GetLevelId()).CancelTimer(self.timer)
            self.timer = None
        self.operation = None
        return {'ok': True, 'samples': list(self.samples), 'keys': list(self.keys), 'truncated': self.truncated}

    def close(self):
        result = self.stop()
        self.UnListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(), 'OnKeyPressInGame', self, self.key)
        return result


module = types.ModuleType(_module_name)
module.Probe = Probe
sys.modules[_module_name] = module
module.probe = api.RegisterSystem('mcpy_optional_unified_input', 'probe', _module_name+'.Probe')
if module.probe is None: raise ValueError('No optional observation system')
_result = {'ok': True}
