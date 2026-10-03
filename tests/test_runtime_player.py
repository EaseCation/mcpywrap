"""有状态玩家适配器：持续动作释放、目标守卫、吃/射及队列时序。"""
import heapq
import types
import unittest
from unittest.mock import Mock, patch
from click.testing import CliRunner
from mcpywrap.cli import cli

from test_runtime_ui import API, GUI
from mcpywrap.mcstudio.runtime_ui_payload import UIController, UIError
from mcpywrap.mcstudio.runtime_player_payload import PlayerController


def item(name,count=1):
    return {'newItemName':name,'newAuxValue':0,'count':count}


class PlayerAPI(API):
    def __init__(self):
        super().__init__()
        self.node.top='hud_screen'
        self.node.screen='hud.hud_screen'
        self.now=0.;self.serial=0;self.scheduled=[]
        self.position=[0.,100.,0.];self.rotation=(0.,0.);self.vector=(0.,0.)
        self.selected=0;self.hunger=10;self.sneaking=False;self.sprinting=False
        self.inventory=[item('minecraft:apple',3),item('minecraft:bow'),item('minecraft:arrow',16)]+[None]*33
        self.target={'type':'Entity','entityId':'cow','hitPosX':0.,'hitPosY':101.,'hitPosZ':3.}
        self.block=('minecraft:stone',0);self.health=10
        self.log=[]
        self.enum=types.SimpleNamespace(ItemPosType=types.SimpleNamespace(INVENTORY=0),
            AttrType=types.SimpleNamespace(HEALTH=0),
            KeyBoardType=types.SimpleNamespace(KEY_W=87,KEY_1=49,KEY_SPACE=32,KEY_LSHIFT=16,KEY_CONTROL=17,KEY_ESCAPE=27,KEY_MOUSE_LEFT=-99))

    def GetLocalPlayerId(self):return 'player'
    def GetMinecraftEnum(self):return self.enum
    def CreatePlayer(self,pid):return self
    def CreatePos(self,pid):return self
    def CreateRot(self,pid):return self
    def CreateActorMotion(self,pid):return self
    def CreateItem(self,pid):return self
    def CreateCamera(self,pid):return self
    def CreateAttr(self,pid):return self
    def CreateBlockInfo(self,pid):return self
    def GetFootPos(self):return tuple(self.position)
    def GetPosition(self):return (self.position[0],self.position[1]+1.62,self.position[2])
    def GetPos(self):return (self.position[0],self.position[1]+1.62,self.position[2])
    def GetRot(self):return self.rotation
    def SetRot(self,rotation):self.rotation=rotation;self.log.append(('look',rotation));return True
    def GetInputVector(self):return self.vector
    def LockInputVector(self,vector):self.vector=vector;self.log.append(('move',vector));return True
    def UnlockInputVector(self):self.vector=(0.,0.);self.log.append(('unlock',));return True
    def BeginSprinting(self):self.sprinting=True
    def EndSprinting(self):self.sprinting=False
    def isSneaking(self):return self.sneaking
    def isSprinting(self):return self.sprinting
    def GetCurrentDimension(self):return 0
    def GetPlayerHunger(self):return self.hunger
    def GetPickRange(self):return 5.7
    def PickFacing(self):return dict(self.target)
    def GetBlock(self,pos):return self.block
    def GetAttrValue(self,attr):return self.health
    def GetSlotId(self):return self.selected
    def GetCarriedItem(self):return self.inventory[self.selected]
    def GetPlayerItem(self,kind,slot):return self.inventory[slot]
    def GetPlayerAllItems(self,kind):return self.inventory
    def GetItemBasicInfo(self,name,aux):return {'itemType':'food' if name=='minecraft:apple' else ''}
    def SimulateJump(self):self.log.append(('jump',))
    def ChangeSneakState(self):self.sneaking=not self.sneaking
    def AddTimer(self,seconds,callback):
        self.serial+=1
        heapq.heappush(self.scheduled,(self.now+seconds,self.serial,callback))
        return self.serial
    def advance(self,seconds):
        until=self.now+seconds
        iterations=0
        while self.scheduled and self.scheduled[0][0]<=until:
            due,_,callback=heapq.heappop(self.scheduled)
            self.now=due;callback();iterations+=1
            if iterations>10000:raise AssertionError('timer loop')
        self.now=until


class Native:
    def __init__(self,api):
        self.api=api;self.using=False;self.started=0.;self.use_return=False
        self.release_error=False;self.dig_ticks=0
    def local_player_select_slot(self,slot):self.api.selected=slot;self.api.log.append(('select',slot));return True
    def local_player_attack_entity(self,entity):self.api.health-=5;self.api.log.append(('attack',entity));return True
    def local_player_build_block(self,*args):self.api.log.append(('use_block',args));return True
    def local_player_use_item(self):
        self.using=True;self.started=self.api.now;self.api.log.append(('use_air',));return self.use_return
    def local_player_is_using_item(self):return self.using
    def local_player_release_using_item(self):
        if self.release_error:raise ValueError('release rejected')
        held=self.api.GetCarriedItem()
        if self.using and held['newItemName']=='minecraft:apple' and self.api.now-self.started>=1.6:
            held['count']-=1;self.api.hunger+=4
        if self.using and held['newItemName']=='minecraft:bow' and self.api.now-self.started>=1:
            self.api.inventory[2]['count']-=1
        self.using=False;self.api.log.append(('release_use',))
    def setSneaking(self,value):self.api.sneaking=value
    def local_player_start_destroy_block(self,*args):self.api.log.append(('dig_start',args));return True,False
    def local_player_continue_destroy_block(self,*args):
        self.dig_ticks+=1
        return True,self.dig_ticks>=2
    def local_player_stop_destroy_block(self,*args):self.api.log.append(('dig_stop',args))


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.api=PlayerAPI();self.gui=GUI(self.api);self.native=Native(self.api)
        self.gui.simulate_keyboard_event=lambda code,state:self.gui.inputs.append((code,None,state)) or True
        self.ui=UIController(self.api,self.gui,'3.10.0.420447',clock=lambda:self.api.now)
        self.ui.events=Mock()
        self.p=PlayerController(self.ui,self.native);self.ui.player=self.p

    def snap(self):return self.p.snapshot()['snapshot']

    def test_snapshot_exposes_human_slots_food_ammo_and_reach(self):
        state=self.p.snapshot()
        self.assertEqual(state['selected_slot'],1)
        self.assertTrue(state['carried']['edible'])
        self.assertEqual(state['arrows'],16)
        self.assertTrue(state['target']['in_reach'])
        self.api.target['hitPosZ']=60
        self.assertFalse(self.p.snapshot()['target']['in_reach'])

    def test_cli_accepts_negative_world_coordinates_without_shell_workarounds(self):
        with patch('mcpywrap.mcstudio.runtime_ui.execute',return_value={'ok':True}) as execute:
            result=CliRunner().invoke(cli,['--local','runtime','player','look-at','-10','65','-20','--session','a'*32,'--json'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(execute.call_args.args[3],{'x':-10.,'y':65.,'z':-20.})
        self.assertEqual(execute.call_args.kwargs['family'],'player')

    def test_look_at_uses_player_eye_in_third_person_and_degree_convention(self):
        self.api.GetPosition=lambda:(0.,106.,-8.)
        result=self.p.look_at(10,101.62,0)
        self.assertEqual(result['state'],'completed')
        self.assertAlmostEqual(self.api.rotation[0],0)
        self.assertAlmostEqual(self.api.rotation[1],-90)

    def test_move_automatically_unlocks_and_restores_sprint(self):
        result=self.p.move(forward=1,right=1,duration_ms=500,sprint=True)
        self.assertEqual(self.api.vector,(-1.,1.))
        self.assertTrue(self.api.sprinting)
        self.api.advance(.6)
        self.assertEqual(self.api.vector,(0.,0.))
        self.assertFalse(self.api.sprinting)
        self.assertTrue(self.p.status(result['id'])['released'])

    def test_other_input_and_menu_are_not_overridden(self):
        self.api.vector=(1,0)
        with self.assertRaises(UIError):self.p.move(forward=1)
        self.api.node.top='pause_screen'
        with self.assertRaises(UIError):self.p.look(0,90)
        self.assertEqual(self.api.log,[])

    def test_known_web_hud_is_allowed_but_menu_over_native_hud_is_not(self):
        self.api.node.top='ui://./hbui/gameplay.html'
        self.p.look(0,90)
        self.api.node.top='ui://./hbui/settings.html'
        with self.assertRaises(UIError):self.p.jump()
        self.api.node.top='hud_screen';self.api.node.screen='pause.pause_screen'
        with self.assertRaises(UIError):self.p.jump()

    def test_key_chord_and_scene_change_release_owned_keys(self):
        result=self.p.key('CTRL+W',hold_ms=500)
        self.assertEqual([x[2] for x in self.gui.inputs],[True,True])
        self.api.node.top='pause_screen';self.ui._changed()
        self.assertEqual([x[0] for x in self.gui.inputs],[17,87,87,17])
        self.assertTrue(self.p.status(result['id'])['released'])
        self.api.advance(1)
        self.assertEqual(len(self.gui.inputs),4)

    def test_mouse_keycodes_are_not_misrepresented_as_keyboard_input(self):
        with self.assertRaises(UIError):self.p.key('MOUSE_LEFT')
        self.assertEqual(self.gui.inputs,[])

    def test_attack_rejects_changed_or_far_targets(self):
        snapshot=self.snap();self.api.target['entityId']='other'
        with self.assertRaises(UIError):self.p.attack(snapshot)
        self.api.target['hitPosZ']=60;snapshot=self.snap()
        with self.assertRaises(UIError):self.p.attack(snapshot)
        self.assertEqual(self.api.log,[])

    def test_attack_and_slot_have_observed_effect_without_duplicate(self):
        snap=self.snap()
        result=self.p.attack(snap,request_id='a'*32)
        self.assertEqual(result['after']['target']['health'],5)
        again=self.p.attack(snap,request_id='a'*32)
        self.assertEqual(again['id'],result['id'])
        self.assertEqual(self.api.health,5)
        self.p.select_slot(2)
        self.assertEqual(self.p.snapshot()['selected_slot'],2)

    def test_false_use_return_does_not_cancel_real_food_use(self):
        result=self.p.eat(self.snap())
        self.assertFalse(result['native_return'])
        self.assertTrue(result['using_item'])
        self.api.advance(2.1)
        self.assertEqual(self.api.hunger,14)
        self.assertEqual(self.api.inventory[0]['count'],2)
        self.assertFalse(self.native.using)

    def test_bow_charges_then_releases_and_wrong_item_is_rejected(self):
        with self.assertRaises(UIError):self.p.shoot(self.snap())
        self.p.select_slot(2)
        result=self.p.shoot(self.snap(),hold_ms=1200)
        self.api.advance(1)
        self.assertTrue(self.native.using)
        self.assertEqual(self.api.inventory[2]['count'],16)
        self.api.advance(.3)
        self.assertFalse(self.native.using)
        self.assertEqual(self.api.inventory[2]['count'],15)
        self.assertTrue(self.p.status(result['id'])['released'])

    def test_release_failure_blocks_ui_and_new_player_input_until_stop(self):
        self.p.eat(self.snap());self.native.release_error=True;self.api.advance(2.1)
        with self.assertRaises(UIError):self.p.look(0,90)
        with self.assertRaises(UIError):self.ui.snapshot()
        self.assertFalse(self.p.stop()['ok'])
        self.native.release_error=False
        self.assertTrue(self.p.stop()['ok'])

    def test_dig_ticks_until_done_and_stops(self):
        self.api.target={'type':'Block','x':0,'y':101,'z':3,'face':2,'hitPosX':0.,'hitPosY':101.,'hitPosZ':3.}
        result=self.p.dig(self.snap())
        self.api.advance(.2)
        self.assertTrue(self.p.status(result['id'])['block_destroyed_reported'])
        self.assertEqual(self.api.log[-1][0],'dig_stop')

    def test_sequence_wait_delay_eat_shoot_and_progress(self):
        plan=[{'action':'select_slot','slot':1,'delay_ms':200},
              {'action':'eat','expect':{'item':'minecraft:apple'}},
              {'action':'wait','duration_ms':200},
              {'action':'select_slot','slot':2},{'action':'shoot'}]
        job=self.p.sequence(plan,request_id='b'*32)
        self.api.advance(.1)
        self.assertEqual(self.api.log,[])
        self.assertEqual(self.p.sequence(plan,request_id='b'*32)['id'],job['id'])
        self.api.advance(6)
        state=self.p.status(job['id'])
        self.assertEqual(state['state'],'completed')
        self.assertEqual(state['index'],len(plan))
        self.assertEqual(self.api.hunger,14)
        self.assertEqual(self.api.inventory[2]['count'],15)
        self.assertEqual([r['step'] for r in state['results']],[1,2,3,4,5])
        self.assertNotIn('before',state['results'][1])
        self.assertEqual(state['results'][1]['changes']['hunger'],{'before':10,'after':14})
        self.assertIn('before',self.p.status(job['id'],details=True)['results'][1])

    def test_queue_blocks_interleaving_and_cancel_prevents_future_steps(self):
        job=self.p.sequence([{'action':'wait','duration_ms':1000},{'action':'jump'}])
        self.api.advance(.1)
        with self.assertRaises(UIError):self.p.look(0,0)
        with self.assertRaises(UIError):self.ui.snapshot()
        self.p.cancel(job['id']);self.api.advance(2)
        self.assertEqual(self.p.status(job['id'])['state'],'cancelled')
        self.assertNotIn(('jump',),self.api.log)

    def test_step_expectation_failure_stops_following_actions(self):
        job=self.p.sequence([{'action':'select_slot','slot':2},{'action':'eat','expect':{'item':'minecraft:apple'}},{'action':'jump'}])
        self.api.advance(3)
        result=self.p.status(job['id'])
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['code'],'expectation_failed')
        self.assertNotIn(('use_air',),self.api.log)
        self.assertNotIn(('jump',),self.api.log)

    def test_external_rotation_override_stops_plan_before_next_action(self):
        job=self.p.sequence([{'action':'look','pitch':0,'yaw':90},{'action':'jump'}])
        self.api.advance(.02)
        self.api.rotation=(0.,0.)
        self.api.advance(1)
        result=self.p.status(job['id'])
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['code'],'rotation_changed')
        self.assertNotIn(('jump',),self.api.log)

    def test_plan_preflight_rejects_bad_later_step_without_partial_effect(self):
        for plan in ([{'action':'jump'},{'action':'look','pitch':100,'yaw':0}],
                     [{'action':'move','forward':1,'duration_ms':0}],
                     [{'action':'wait','duration_ms':10000}]*13):
            with self.subTest(plan=plan), self.assertRaises(UIError):self.p.sequence(plan)
        self.api.advance(200)
        self.assertEqual(self.api.log,[])

    def test_plan_is_copied_and_same_request_cannot_change_it(self):
        plan=[{'action':'select_slot','slot':2}]
        job=self.p.sequence(plan,request_id='c'*32)
        plan[0]['slot']=1
        with self.assertRaises(UIError):self.p.sequence(plan,request_id='c'*32)
        self.api.advance(1)
        self.assertEqual(self.api.selected,1)
        self.assertEqual(self.p.status(job['id'])['state'],'completed')

    def test_ui_transition_cancels_sequence_and_restores_sneak(self):
        self.api.sneaking=False
        job=self.p.sequence([{'action':'sneak','duration_ms':2000},{'action':'jump'}])
        self.api.advance(.1);self.assertTrue(self.api.sneaking)
        self.api.node.top='pause_screen';self.ui._changed();self.api.advance(3)
        self.assertFalse(self.api.sneaking)
        self.assertEqual(self.p.status(job['id'])['state'],'cancelled')
        self.assertNotIn(('jump',),self.api.log)


if __name__=='__main__':unittest.main()
