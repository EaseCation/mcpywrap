import unittest
from unittest.mock import patch, Mock
import psutil
from mcpywrap_core import _process_identity as subject

class RestrictedProcessIdentity(unittest.TestCase):
    def test_unreadable_system_boot_time_uses_process_start_ticks(self):
        process=Mock()
        process.create_time.side_effect=psutil.AccessDenied(42)
        process.exe.return_value='/usr/bin/python3'
        with patch.object(subject.sys,'platform','linux'), patch.object(subject.psutil,'Process',return_value=process), patch.object(subject,'proc_stat',return_value={'start_ticks':123,'state':'S'}):
            record=subject.identity(42)
            self.assertEqual(record,{'pid':42,'start_ticks':123,'executable':'/usr/bin/python3'})
            self.assertTrue(subject.alive(record))
            self.assertFalse(subject.alive(dict(record,start_ticks=124)))

    def test_stat_parser_handles_parentheses_and_spaces_in_process_name(self):
        # Fields 3..22: state, ppid, pgrp, ... starttime.
        fields=['S','7','11']+['0']*16+['98765']
        with patch('pathlib.Path.read_text',return_value='42 (worker (nested) name) '+' '.join(fields)):
            self.assertEqual(subject.proc_stat(42),{'pid':42,'state':'S','parent':7,'group':11,'start_ticks':98765})

    def test_unknown_permissions_are_not_mistaken_for_dead_process(self):
        with patch.object(subject,'proc_stat',side_effect=PermissionError('restricted')):
            with self.assertRaises(PermissionError):subject.alive({'pid':42,'start_ticks':1})

    def test_existing_desktop_identity_shape_stays_compatible(self):
        process=Mock();process.create_time.return_value=123.5;process.exe.return_value='python.exe'
        with patch.object(subject.psutil,'Process',return_value=process):
            self.assertEqual(subject.identity(42),{'pid':42,'created_at':123.5,'executable':'python.exe'})

    def test_non_linux_access_denied_does_not_attempt_procfs(self):
        process=Mock();process.create_time.side_effect=psutil.AccessDenied(42)
        for platform in ('win32','darwin'):
            with self.subTest(platform=platform),patch.object(subject.sys,'platform',platform),patch.object(subject.psutil,'Process',return_value=process),patch.object(subject,'proc_stat') as proc:
                with self.assertRaises(psutil.AccessDenied):subject.identity(42)
                proc.assert_not_called()
