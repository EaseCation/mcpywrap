"""可选实机测试，不参与默认 unittest：验证吃东西/射箭队列并恢复朝向与选槽。

测试会消耗一份食物和一支箭；不创建物品、不切游戏模式、不停止传入会话。
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from manual_runtime_ui import foreground
from manual.runtime_controls.support import invoke_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--session',required=True)
    parser.add_argument('--food-slot',type=int,required=True)
    parser.add_argument('--bow-slot',type=int,required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--require-background',action='store_true')
    args=parser.parse_args(); output=Path(args.output)
    if args.require_background and sys.platform != 'win32':
        parser.error('--require-background 只验证 Windows 前台；macOS 请省略')
    if output.exists():raise ValueError('输出必须是新文件')
    prefix=[sys.executable,'-X','utf8','-m','mcpywrap','--local','--project',args.project]
    history=[]
    def call(*command):
        result,code=invoke_json(prefix+list(command)+['--session',args.session,'--json'],timeout=60)
        history.append({'command':command,'result':result})
        if code or not result.get('ok'):raise RuntimeError(result)
        return result
    def player(*command):return call('runtime','player',*command)
    game=call('status')['game']
    observations=[foreground()];stop=threading.Event()
    if args.require_background and observations[0]['pid']==game['pid']:raise ValueError('请保持其他应用前台')
    def monitor():
        while not stop.wait(.01):
            state=foreground()
            if state!=observations[-1]:observations.append(state)
    watcher=threading.Thread(target=monitor);watcher.start()
    before=None;error=None;after=None
    try:
        call('runtime','install')
        before=player('snapshot')
        food=before['hotbar'][args.food_slot-1]['item']
        bow=before['hotbar'][args.bow_slot-1]['item']
        assert food and bow and bow['name']=='minecraft:bow'
        assert before['hunger']<20 and before['arrows']>0
        plan=[{'action':'select_slot','slot':args.food_slot},
              {'action':'eat','hold_ms':2000,'expect':{'item':food['name']}},
              {'action':'wait','duration_ms':200},
              {'action':'select_slot','slot':args.bow_slot},
              {'action':'look','pitch':-30,'yaw':before['rotation']['yaw'],'delay_ms':100},
              {'action':'shoot','hold_ms':1200,'expect':{'item':'minecraft:bow'}}]
        rid=uuid.uuid4().hex
        job=player('sequence','--steps',json.dumps(plan),'--request-id',rid)
        deadline=time.monotonic()+15
        while job['state']=='pending' and time.monotonic()<deadline:
            time.sleep(.25)
            job=player('status','--operation',rid)
        assert job['state']=='completed' and job['index']==len(plan)
        after=player('snapshot')
        assert after['hunger']>before['hunger']
        assert after['hotbar'][args.food_slot-1]['item']['count']==food['count']-1
        assert after['arrows']==before['arrows']-1
        duplicate=player('sequence','--steps',json.dumps(plan),'--request-id',rid)
        assert duplicate['id']==rid and duplicate['state']=='completed'
        unchanged=player('snapshot')
        assert unchanged['arrows']==after['arrows'] and unchanged['hunger']==after['hunger']
    except Exception as exc:error=str(exc)
    finally:
        try:
            player('stop')
            if before:
                player('select-slot',str(before['selected_slot']))
                player('look','--pitch',str(before['rotation']['pitch']),'--yaw',str(before['rotation']['yaw']))
        except Exception as exc:error=(error or '')+'\n恢复失败：'+str(exc)
        stop.set();watcher.join()
        if args.require_background and any(s['pid']==game['pid'] for s in observations):error=(error or '')+'\n游戏曾成为前台'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({'ok':error is None,'error':error,'session':args.session,'game_pid':game['pid'],
            'before':before,'after':after,'observations':observations,'history':history},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':error is None,'error':error,'calls':len(history),'output':str(output)},ensure_ascii=False))
    return int(error is not None)


if __name__=='__main__':raise SystemExit(main())
