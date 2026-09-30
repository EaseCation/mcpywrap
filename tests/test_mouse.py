"""Mouse geometry and bounded input release; never calls the real Windows desktop."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mcpywrap.mcstudio import window


class MouseTests(unittest.TestCase):
    def target(self):
        target = window.GameWindow.__new__(window.GameWindow)
        target.foreground = Mock()
        target.check_foreground = Mock()
        target.client_area = Mock(return_value=(800, 600, SimpleNamespace(x=-1200, y=100)))
        target.user = Mock()
        target.user.GetAsyncKeyState.return_value = 0
        target.user.GetSystemMetrics.side_effect = {76: -1920, 77: 0, 78: 3840, 79: 1080}.get
        events = []
        def send(count, pointer, size):
            event = pointer._obj
            if event.kind == 0:
                events.append(('mouse', event.mouse.dx, event.mouse.dy, event.mouse.data, event.mouse.flags))
            else:
                events.append(('key', event.keyboard.vk, event.keyboard.flags))
            return 1
        target.user.SendInput.side_effect = send
        return target, events

    def test_negative_monitor_coordinates_and_modifier_click(self):
        target, events = self.target()
        result = target.mouse('click', x=400, y=200, width=800, height=600, keys=['SHIFT'], duration_ms=20)
        self.assertEqual(events[0], ('key', 0xA0, 0))
        move = events[1]
        self.assertEqual(move[1:3], (round(1120*65535/3839), round(300*65535/1079)))
        self.assertEqual(move[-1], 0xC001)
        self.assertEqual([v[-1] for v in events[2:]], [2, 4, 2])
        self.assertFalse(result['effect_verified'])

    def test_dimension_and_bounds_rejected_before_input(self):
        target, events = self.target()
        for args in ({'width': 801, 'height': 600, 'x': 1, 'y': 1},
                     {'width': 800, 'height': 600, 'x': -1, 'y': 1},
                     {'width': 800, 'height': 600, 'x': 800, 'y': 1}):
            with self.assertRaises(ValueError):
                target.mouse('click', **args)
        self.assertEqual(events, [])

    def test_current_click_does_not_move_captured_game_cursor(self):
        target,events=self.target();target.game={'pid':123};target.owner=Mock(return_value=123)
        def cursor(pointer):pointer._obj.x=-1000;pointer._obj.y=300;return True
        target.user.GetCursorPos.side_effect=cursor
        target.mouse('click-current',width=800,height=600,duration_ms=20)
        self.assertEqual([v[-1] for v in events],[2,4])
        events.clear();target.owner.return_value=999
        with self.assertRaisesRegex(ValueError,'遮挡'):
            target.mouse('click-current',width=800,height=600)
        self.assertEqual(events,[])

    def test_current_click_rejects_cursor_outside_game(self):
        target,events=self.target()
        def cursor(pointer):pointer._obj.x=0;pointer._obj.y=0;return True
        target.user.GetCursorPos.side_effect=cursor
        with self.assertRaisesRegex(ValueError,'客户区'):
            target.mouse('click-current',width=800,height=600)
        self.assertEqual(events,[])

    def test_drag_failure_releases_button_and_keys(self):
        target, events = self.target()
        original_send=target.user.SendInput.side_effect
        def lose_focus_after_down(count,pointer,size):
            result=original_send(count,pointer,size)
            if pointer._obj.kind==0 and pointer._obj.mouse.flags==2:
                target.check_foreground.side_effect=ValueError('focus lost')
            return result
        target.user.SendInput.side_effect=lose_focus_after_down
        with self.assertRaisesRegex(ValueError, 'focus lost'):
            target.mouse('drag', x=1, y=1, to_x=100, to_y=100, width=800, height=600, keys=['CTRL'])
        self.assertEqual(events[-2][-1], 4)
        self.assertEqual(events[-1], ('key', 0xA2, 2))

    def test_modifier_lead_time_and_safe_release_before_click(self):
        target,events=self.target()
        clock=[0.0];down=[];original_send=target.user.SendInput.side_effect
        def send(count,pointer,size):
            if pointer._obj.kind==0 and pointer._obj.mouse.flags==2:down.append(clock[0])
            return original_send(count,pointer,size)
        target.user.SendInput.side_effect=send
        with patch.object(window.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(window.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            target.mouse('click',x=20,y=20,width=800,height=600,keys=['SHIFT'])
        self.assertGreaterEqual(down[0],.15)
        target,events=self.target()
        target.check_foreground.side_effect=[None,None,ValueError('focus lost')]
        with self.assertRaisesRegex(ValueError,'focus lost'):
            target.mouse('click',x=20,y=20,width=800,height=600,keys=['SHIFT'])
        self.assertEqual(events[-1],('key',0xA0,2))
        self.assertFalse(any(e[0]=='mouse' and e[-1]==2 for e in events))

    def test_relative_movement_sums_to_requested_delta(self):
        target, events = self.target()
        target.mouse('relative', dx=31, dy=-7, duration_ms=40)
        self.assertEqual(sum(v[1] for v in events), 31)
        self.assertEqual(sum(v[2] for v in events), -7)
        self.assertTrue(all(v[-1] == 1 for v in events))

    def test_scroll_and_double_click(self):
        target, events = self.target()
        target.mouse('scroll', x=20, y=20, width=800, height=600, delta=-120)
        self.assertEqual(events[-1][3:], ((-120) & 0xFFFFFFFF, 0x800))
        events.clear()
        target.mouse('double-click', x=20, y=20, width=800, height=600, duration_ms=20)
        self.assertEqual([v[-1] for v in events], [0xC001, 2, 4, 2, 4])

    def test_cancel_after_mouse_down_releases(self):
        target, events = self.target()
        with patch.object(window.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                target.mouse('click', x=20, y=20, width=800, height=600)
        self.assertEqual(events[-1][-1], 4)


if __name__ == '__main__':
    unittest.main()
