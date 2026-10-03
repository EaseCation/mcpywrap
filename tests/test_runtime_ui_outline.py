"""语义分组不复制深层布局；关联、分页和动作定位仍保持一致。"""
import json
import unittest
from unittest.mock import Mock

from mcpywrap.mcstudio.runtime_ui_outline import prepare_ui_outline, render_ui_outline
from mcpywrap.mcstudio.runtime_ui_payload import UIController, UIError
from test_runtime_ui import API, GUI, ROOT


def row(path, role, name, box, **extra):
    data = {'path':path, 'role':role, 'name':name, 'bounds':box, 'visible_bounds':box,
            'in_view':True, 'ambiguous':False, 'parent_path':None, 'enabled':None}
    if role == 'label':
        data['text'] = name
    data.update(extra)
    return data


def settings_rows():
    nav = ROOT+'/layout/nav/scroll_touch/scroll_view'
    content = ROOT+'/layout/content_area/scrolling_panel/scroll_touch/scroll_view'
    return [
        row(ROOT+'/layout/dialog_titles/dialog_title_label','label','设置',(0,0,180,15)),
        row(ROOT+'/layout/dialog_titles/section_title_label','label','游戏设置',(220,0,490,15)),
        row(nav,'scroll','scroll_view',(0,20,180,380),value=0,container=ROOT+'/layout/nav'),
        row(nav+'/list/world/group_label','label','世界',(4,30,175,40)),
        row(nav+'/list/world/game/button','toggle','游戏',(4,42,175,72),value=True),
        row(nav+'/list/world/debug/button','toggle','调试',(4,74,175,104),value=False),
        row(nav+'/list/controls/group_label','label','控制',(4,110,175,120)),
        row(nav+'/list/controls/keyboard/button','toggle','键盘和鼠标',(4,122,175,152),value=False),
        row(nav+'/list/controls/pad/button','toggle','手柄',(4,154,175,184),value=False),
        row(content,'scroll','scroll_view',(200,20,510,380),value=0,container=ROOT+'/layout/content_area/scrolling_panel'),
        row(content+'/form/name/option_generic_core/label','label','世界名称',(205,25,500,35)),
        row(content+'/form/name/option_generic_core/input','edit','世界名称',(205,37,500,67),value='示例'),
        row(content+'/form/name/option_generic_core/input/display_text','label','示例',(208,45,497,55)),
        row(content+'/form/difficulty/option_generic_core/label','label','难度',(205,74,500,84)),
        row(content+'/form/difficulty/option_generic_core/value/label','label','普通',(215,95,480,105)),
        row(content+'/form/world_preferences_label/text','label','世界首选项',(205,125,300,135)),
        row(content+'/form/map/option_generic_core/toggle','toggle','初始地图',(205,145,235,165),value=False),
        row(content+'/form/map/option_generic_core/label','label','初始地图',(240,149,500,159)),
        row(content+'/form/chest/option_generic_core/toggle','toggle','奖励箱',(205,175,235,195),value=True),
        row(content+'/form/chest/option_generic_core/label','label','奖励箱',(240,179,500,189)),
    ]


def render(rows, predicate=lambda r:True):
    model = prepare_ui_outline(rows)
    records, stored = [], {}
    for index, item in enumerate([r for r in model['rows'] if predicate(r)],1):
        record = {k:item[k] for k in ('role','name','in_view','ambiguous')}
        record.update(id=index, parent=item['outline_parent'], depth=item['outline_depth'])
        for key in ('value','description'):
            if key in item:
                record[key] = item[key]
        records.append(record)
        stored[index] = item
    tree, groups = render_ui_outline(model,records,stored)
    return model, tree, records, groups


class OutlineTests(unittest.TestCase):
    def test_settings_navigation_sections_and_fields_are_shallow(self):
        model, tree, records, groups = render(settings_rows())
        self.assertEqual(model['title'],'设置')
        self.assertEqual({g['name'] for g in groups},{'导航','世界','控制','游戏设置','世界首选项'})
        self.assertLessEqual(max(r['depth'] for r in records),3)
        self.assertIn('edit 世界名称 = 示例',tree)
        self.assertEqual(tree.count('世界名称'),1)
        self.assertEqual(tree.count('初始地图'),1)
        self.assertIn('label 难度 = 普通',tree)
        navigation = next(g for g in groups if g['name']=='导航')
        controls = next(g for g in groups if g['name']=='控制')
        keyboard = next(r for r in records if r['name']=='键盘和鼠标')
        self.assertEqual(controls['parent'],navigation['id'])
        self.assertEqual(keyboard['parent'],controls['id'])

    def test_layout_wrapper_depth_never_becomes_output_depth(self):
        prefix=ROOT+'/'+'/'.join('panel'+str(i) for i in range(30))
        _, tree, records, _ = render([
            row(prefix+'/first','button','确定',(10,20,100,50)),
            row(prefix+'/second','button','取消',(110,20,200,50))])
        self.assertNotIn('panel',tree)
        self.assertEqual({r['depth'] for r in records},{1})

    def test_separate_cards_do_not_merge_identical_labels(self):
        rows=[]
        for card, title, x in [('a','装备',0),('b','材料',220)]:
            prefix=ROOT+'/cards/'+card
            rows.extend([row(prefix+'/title','label',title,(x,0,x+200,15)),
                         row(prefix+'/use','button','使用',(x,20,x+90,50)),
                         row(prefix+'/drop','button','丢弃',(x+100,20,x+190,50))])
        _, tree, records, groups=render(rows)
        self.assertEqual({g['name'] for g in groups},{'装备','材料'})
        uses=[r for r in records if r['name']=='使用']
        self.assertNotEqual(uses[0]['parent'],uses[1]['parent'])
        self.assertEqual(tree.count('button 使用'),2)

    def test_columns_stay_together_when_left_menu_starts_lower(self):
        scroll=ROOT+'/right/scroll_touch/scroll_view'
        rows=[row(ROOT+'/left/start','button','开始',(0,100,100,130)),
              row(ROOT+'/left/settings','button','设置',(0,140,100,170)),
              row(scroll,'scroll','scroll_view',(300,0,500,300),value=0),
              row(scroll+'/player','button','玩家',(310,20,490,50))]
        _,tree,records,groups=render(rows)
        self.assertLess(tree.index('button 开始'),tree.index('scroll'))
        self.assertLess(tree.index('button 设置'),tree.index('scroll'))
        self.assertEqual({g['name'] for g in groups},{'操作','滚动区域'})

    def test_caption_affinity_uses_local_row_not_other_column(self):
        rows=[]
        for name,x in [('姓名',0),('年龄',250)]:
            prefix=ROOT+'/form/row_'+name
            rows.extend([row(prefix+'/caption','label',name,(x,10,x+100,20)),
                         row(prefix+'/input','edit','input',(x,24,x+200,54),value='值')])
        model, tree, records, _=render(rows)
        self.assertEqual({r['name'] for r in records},{'姓名','年龄'})
        self.assertNotIn('caption',tree)
        self.assertEqual(len(model['rows']),2)

    def test_distant_dialog_message_is_not_renamed_as_button(self):
        _, tree, records, _=render([
            row(ROOT+'/dialog/message','label','确认后将退出当前世界',(0,10,300,60)),
            row(ROOT+'/dialog/ok','button','确定',(100,200,200,230))])
        self.assertEqual(len(records),2)
        self.assertEqual(next(r for r in records if r['role']=='button')['name'],'确定')
        self.assertIn('确认后将退出当前世界',tree)

    def test_sections_without_scrollers_do_not_need_layout_wrappers(self):
        rows=[row(ROOT+'/form/group_label_1','label','声音',(0,10,200,20)),
              row(ROOT+'/form/volume','slider','音量',(0,30,200,40),value=.5),
              row(ROOT+'/form/music','slider','音乐',(0,50,200,60),value=.8),
              row(ROOT+'/form/group_label_2','label','显示',(0,80,200,90)),
              row(ROOT+'/form/brightness','slider','亮度',(0,100,200,110),value=.6)]
        _,_,records,groups=render(rows)
        self.assertEqual({g['name'] for g in groups},{'声音','显示'})
        self.assertNotEqual(next(r for r in records if r['name']=='音量')['parent'],
                            next(r for r in records if r['name']=='亮度')['parent'])
        self.assertLessEqual(max(r['depth'] for r in records),2)

    def test_filtered_leaf_keeps_non_actionable_ancestor_context(self):
        _,tree,records,groups=render(settings_rows(),lambda r:r['name']=='键盘和鼠标')
        self.assertIn('导航',tree)
        self.assertIn('控制',tree)
        self.assertEqual(len(records),1)
        self.assertTrue(all(g['context_only'] and g['node_id'] is None for g in groups))
        self.assertEqual(tree.count('[1]'),1)
        self.assertNotIn('游戏设置',tree)

    def test_offscreen_readonly_value_is_not_fabricated_on_visible_caption(self):
        rows=[row(ROOT+'/field_1/caption','label','名称',(0,0,100,10)),
              row(ROOT+'/field_1/value','label','屏外值',(0,500,100,510),in_view=False)]
        model, _, _, _=render(rows)
        self.assertEqual(len(model['rows']),2)
        self.assertNotIn('value',model['rows'][0])

    def test_outline_does_not_mutate_fingerprint_source(self):
        rows=settings_rows()
        original=json.dumps(rows,ensure_ascii=False,sort_keys=True)
        render(rows)
        self.assertEqual(json.dumps(rows,ensure_ascii=False,sort_keys=True),original)

    def test_public_snapshot_paging_and_actions_keep_original_targets(self):
        api=API();gui=GUI(api)
        api.node.data={ROOT:{'kind':10,'size':(512,384)}}
        kinds={'label':9,'scroll':14,'toggle':19,'edit':4}
        for r in settings_rows():
            prefix=r['path']
            while prefix!=ROOT:
                api.node.data.setdefault(prefix,{'kind':10,'size':(512,384)})
                prefix=prefix.rsplit('/',1)[0]
            x,y,right,bottom=r['bounds']
            api.node.data[r['path']]={'kind':kinds[r['role']],'pos':(x,y),'size':(right-x,bottom-y),
                                     'text':r.get('text',''),'value':r.get('value')}
            if r['role'] not in ('label','scroll'):
                api.node.data[r['path']+'/caption']={'kind':9,'pos':(x,y),'size':(right-x,bottom-y),'text':r['name']}
            if 'container' in r:
                api.node.data[r['container']]['scroll']=True
        ui=UIController(api,gui,'3.10.0.420447');ui.events=Mock()
        snapshot=ui.snapshot(query='控制',limit=1,offset=1,details=True)
        self.assertIn('控制',snapshot['tree'])
        self.assertIn('导航',snapshot['tree'])
        self.assertEqual(snapshot['nodes'][0]['name'],'键盘和鼠标')
        self.assertTrue(snapshot['truncated'])
        self.assertEqual(snapshot['next_offset'],2)
        target=snapshot['nodes'][0]
        ui.click(target['id'],snapshot['snapshot'])
        self.assertEqual(gui.inputs[0],(179,274,0))
        api.tick()
        current=ui.snapshot(query='键盘和鼠标')
        with self.assertRaises(UIError):ui.click(current['groups'][0]['id'],current['snapshot'])


if __name__=='__main__':unittest.main()
