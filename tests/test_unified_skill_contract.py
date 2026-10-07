"""技能中的实际新协议示例可被公开协议解析；能力发现不受旧命令隐藏影响。"""
import importlib.util
import json
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch

from mcpywrap.input_plan import normalize_input_plan, InputPlanError

ROOT = Path(__file__).resolve().parents[1]


class UnifiedSkillContract(unittest.TestCase):
    def test_published_skill_json_examples_are_executable_plans(self):
        guide = ROOT/'skills/mcpywrap/references/runtime-input.md'
        snippets = re.findall(r'```json\s*\n(.*?)\n```', guide.read_text(encoding='utf8'), re.S)
        self.assertTrue(snippets, 'Agent guide needs an actual plan example')
        for snippet in snippets:
            normalized = normalize_input_plan(json.loads(snippet))
            self.assertEqual(normalized['backend'], 'game')
            self.assertTrue(normalized['steps'])

    def test_legacy_json_dialects_are_not_accepted_as_new_protocol(self):
        for legacy in ([{'action': 'key', 'keys': 'W', 'hold_ms': 100}],
                       {'schema_version': 1, 'clock': 'monotonic_ms', 'events': []},
                       {'schema_version': 1, 'steps': [{'type': 'key_down', 'key': 'W', 'at_ms': 0}]},
                       {'schema_version': 1, 'steps': [{'action': 'key', 'keys': ['W'], 'hold_ms': 100}]}):
            with self.subTest(plan=legacy), self.assertRaises(InputPlanError): normalize_input_plan(legacy)

    def test_bootstrap_detects_new_protocol_and_hidden_compatibility_independently(self):
        spec = importlib.util.spec_from_file_location('unified_bootstrap', ROOT/'skills/mcpywrap/scripts/bootstrap.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        def invoke(args, **kwargs):
            if '--capabilities' in args:
                return Mock(returncode=0, stdout=json.dumps({'ok': True, 'execution': 'local',
                    'capabilities': ['key', 'mouse', 'input-sequence'], 'host': {'backend': 'windows'}}), stderr='')
            help_by_path = {('runtime', '--help'): 'Commands:\n  input Input\n  py Execute\n',
                ('runtime', 'input', '--help'): 'Commands:\n'+''.join('  '+name+' Description\n' for name in ('capabilities', 'observe', 'run', 'status', 'cancel', 'stop')),
                ('runtime', 'ui', '--help'): 'Commands:\n'+''.join('  '+name+' Description\n' for name in ('install', 'snapshot', 'click', 'status')),
                ('runtime', 'player', '--help'): 'Commands:\n'+''.join('  '+name+' Description\n' for name in ('snapshot', 'move', 'eat', 'shoot', 'sequence')),
                ('run', '--help'): '--detach --no-gui'}
            for suffix, content in help_by_path.items():
                if tuple(args[-len(suffix):]) == suffix: return Mock(returncode=0, stdout=content, stderr='')
            return Mock(returncode=0, stdout='--local --remote --project --non-interactive --json status logs stop package\n  runtime Control\n', stderr='')
        with patch.object(module, 'invoke', side_effect=invoke):
            result = module.capabilities('mcpy', local=True)
        self.assertTrue({'unified-input', 'runtime-ui', 'runtime-player'} <= set(result['capabilities']))
        self.assertTrue({'key', 'mouse', 'input-sequence'} <= set(result['local_capabilities']))


if __name__ == '__main__': unittest.main()
