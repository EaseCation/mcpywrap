"""Windows LAN 定位与菜单决策的离线回归；不启动游戏、不读取真实进程。"""
import importlib.util
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory

from mcpywrap_core.mcstudio.lan_locator import LocatorError, locate_port
from mcpywrap_core.runtime.lan_menu import choose


class Image:
    def __init__(self, code, base=0x1000):
        self.code,self.base=code,base
        self.sections=[(base,len(code),True)]
        self.functions=[(base,base+len(code))]
    def read(self,rva,size):
        return self.code[rva-self.base:rva-self.base+size]


@unittest.skipUnless(importlib.util.find_spec('capstone'), 'Windows desktop disassembler dependency')
class LocatorTests(unittest.TestCase):
    # 人工生成的最小指令夹具，不包含任何引擎二进制片段。
    def recipe(self):
        return bytes.fromhex('55 48 89 e5 b8 7f1d0000 66 8945a8 c745ac d0070000 '
                             'b8 efbeadde 488945a0 488d4da0 e8 00000000 5d c3')
    def test_relocated_initializer_is_found_without_version_or_address_table(self):
        for base in (0x1000,0x6164000,0x9400000):
            site=locate_port(Image(self.recipe(),base))
            self.assertEqual(site.operand_rva,base+5)
            self.assertEqual(site.expected,bytes.fromhex('b87f1d0000'))
    def test_port_number_in_call_displacement_is_not_an_instruction(self):
        with self.assertRaises(LocatorError):
            locate_port(Image(bytes.fromhex('e8 7f1d0000 c3')))
    def test_missing_protocol_magic_is_rejected(self):
        with self.assertRaises(LocatorError):
            locate_port(Image(self.recipe().replace(bytes.fromhex('efbeadde'),b'\0'*4)))
    def test_multiple_valid_initializers_are_rejected(self):
        code=self.recipe()
        image=Image(code+code)
        image.functions=[(0x1000,0x1000+len(code)),(0x1000+len(code),0x1000+2*len(code))]
        with self.assertRaises(LocatorError): locate_port(image)
    def test_non_executable_data_is_rejected(self):
        image=Image(self.recipe()); image.sections=[(0x1000,len(image.code),False)]
        with self.assertRaises(LocatorError): locate_port(image)


class MenuTests(unittest.TestCase):
    def view(self,*texts):
        return {'width':1920,'height':1080,'lines':[
            {'text':text,'bounds':[300,200+i*80,650,230+i*80]} for i,text in enumerate(texts)]}
    def test_choose_owned_host_from_other_lan_advertisements(self):
        action=choose(self.view('Powered by Nemisys','mcpy_other','mcpy_49e29Ø9e 的世界'),'mcpy_49e2909e')
        self.assertEqual(action.kind,'host')
        self.assertEqual(action.point,(475,375))
    def test_no_fuzzy_identity_selection(self):
        self.assertIsNone(choose(self.view('mcpy_49e2909f'),'mcpy_49e2909e'))
        self.assertIsNone(choose(self.view('mcpy_49e29'),'mcpy_49e2909e'))
        self.assertEqual(choose(self.view('mcpy_5b796S4d'),'mcpy_5b79684d').kind,'host')
    def test_ambiguous_host_is_not_clicked(self):
        with self.assertRaises(ValueError): choose(self.view('mcpy_abcd1234','mcpy_abcd1234'),'mcpy_abcd1234')
    def test_download_requires_previously_selected_host_and_prefers_all(self):
        view=self.view('全部下载并加入 - 0.00MB','下载必要资源包并加入 - 0.00MB')
        self.assertIsNone(choose(view,'mcpy_abcd1234'))
        self.assertEqual(choose(view,'mcpy_abcd1234',True).text,'全部下载并加入 - 0.00MB')
    def test_continue_only_in_expected_online_warning(self):
        self.assertIsNone(choose(self.view('Continue'),'mcpy_abcd1234',True))
        self.assertEqual(choose(self.view('Online play is not rated','Continue'),'mcpy_abcd1234',True).kind,'confirm')
    def test_bootstrap_exit_is_not_used_during_normal_join(self):
        self.assertIsNone(choose(self.view('保存并退出'),'mcpy_abcd1234'))
        self.assertEqual(choose(self.view('保 存 并 退 出'),'mcpy_abcd1234',bootstrap=True).kind,'leave_bootstrap')
    def test_invalid_bounds_are_rejected(self):
        view=self.view('Play');view['lines'][0]['bounds'][0]=-1
        with self.assertRaises(ValueError): choose(view,'mcpy_abcd1234')


class MemoryPatchTests(unittest.TestCase):
    def image(self, fail=False):
        from mcpywrap_core.mcstudio.lan_memory import ProcessImage
        from mcpywrap_core.mcstudio.lan_locator import PortSite
        image=ProcessImage.__new__(ProcessImage)
        image.base=0;image.handle=1
        memory=bytearray(bytes.fromhex('b87f1d0000'))
        image.read=lambda rva,size:bytes(memory[rva:rva+size])
        image.suspended=lambda:nullcontext()
        def protect(handle,address,size,new,old):
            old._obj.value=0x20
            return True
        writes=[]
        def write(handle,address,data,size,count):
            writes.append(bytes(data))
            n=2 if fail and len(writes)==1 else size
            memory[address:address+n]=data[:n];count._obj.value=n
            return n==size
        image.kernel=Mock()
        image.kernel.VirtualProtectEx.side_effect=protect
        image.kernel.WriteProcessMemory.side_effect=write
        return image,PortSite(0,1,0,bytes(memory)),memory,writes
    def test_patch_changes_only_port_and_restores_page_protection(self):
        image,site,memory,writes=self.image()
        image.patch(site,65000)
        self.assertEqual(memory,bytes.fromhex('b8e8fd0000'))
        self.assertEqual(image.kernel.VirtualProtectEx.call_args.args[3],0x20)
    def test_partial_write_rolls_back_before_resuming(self):
        image,site,memory,writes=self.image(True)
        with self.assertRaises(LocatorError):image.patch(site,65000)
        self.assertEqual(memory,site.expected)
        self.assertEqual(len(writes),2)
        self.assertEqual(image.kernel.VirtualProtectEx.call_args.args[3],0x20)
    def test_stale_instruction_is_never_written(self):
        image,site,memory,writes=self.image()
        memory[0]=0x90
        with self.assertRaises(LocatorError):image.patch(site,65000)
        self.assertEqual(writes,[])
        image.kernel.VirtualProtectEx.assert_not_called()


class JoinLifecycleTests(unittest.TestCase):
    def setUp(self):
        from mcpywrap_core.runtime.windows_join import AutoJoin
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data={'project':self.temp.name,'session':'a'*32,'game':{},'network':{
            'bootstrap_level':'setup','lan_target':{'network_id':'42','level':'world','name':'mcpy_abcd1234','port':60000}}}
        self.channel=Mock();self.channel.ready.return_value=True
        self.channel.connected.is_set.return_value=True
        self.joiner=AutoJoin(self.data,self.channel)
        self.joiner.host_valid=Mock()
        self.joiner.stop.wait=Mock()
    def test_target_hud_is_required_before_publishing_joined(self):
        self.channel.execute.return_value={'state':'completed','value':{'screen':'hud_screen','level':'world','network_id':'42'}}
        self.joiner.run()
        self.assertEqual(self.joiner.status()['state'],'joined')
        self.assertFalse(self.channel.joining)
    def test_matching_network_id_with_wrong_world_fails(self):
        self.channel.execute.return_value={'state':'completed','value':{'screen':'hud_screen','level':'other','network_id':'42'}}
        self.joiner.run()
        self.assertEqual(self.joiner.status()['state'],'failed')
    def test_unknown_probe_is_not_replayed(self):
        self.channel.execute.return_value={'state':'unknown','error':'timeout'}
        self.joiner.run()
        self.assertEqual(self.joiner.status()['state'],'failed')
        self.channel.execute.assert_called_once()
    def test_cancel_before_start_sends_no_input(self):
        self.joiner.stop.set()
        self.joiner.run()
        self.assertEqual(self.joiner.status()['state'],'cancelled')
        self.channel.execute.assert_not_called()
    def test_original_host_exit_prevents_guest_input(self):
        self.joiner.host_valid.side_effect=ValueError('host exited')
        self.joiner.run()
        self.assertEqual(self.joiner.status()['state'],'failed')
        self.channel.execute.assert_not_called()
