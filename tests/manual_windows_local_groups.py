"""可选 Windows 实机验收：两个项目自动双端加入、Mod 加载与客机重启。

不进入默认测试/CI。输出目录必须尚不存在；只清理本次启动的组，保留全部证据。
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--engine-version',action='append',required=True)
    parser.add_argument('--command',default='mcpy')
    parser.add_argument('--timeout',type=float,default=360)
    args=parser.parse_args()
    if os.name!='nt' or len(args.engine_version)!=2:
        parser.error('需要 Windows，并明确指定两个 --engine-version（可以相同）')
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    report={'engines':args.engine_version,'commands':[],'groups':[],'cleanup':[],'passed':False}
    def save():
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def invoke(project,*parts,read_only=False):
        command=[args.command,'--local','--project',str(project),'--non-interactive',*parts,'--json']
        for attempt in range(5):
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=args.timeout+30)
            stdout=result.stdout.decode('utf-8','replace')
            try:
                value=json.loads(stdout.splitlines()[-1])
            except (ValueError,IndexError):
                value={'ok':False,'error':stdout}
            report['commands'].append({'argv':command,'exit_code':result.returncode,'result':value,
                                       'stderr':result.stderr.decode('utf-8','replace'),'at':time.time()})
            save()
            if not read_only or value.get('error')!='已有游戏脚本正在执行':
                break
            time.sleep(.4)
        return value
    def require(value):
        if not value.get('ok'):
            raise RuntimeError(value.get('error') or repr(value))
        return value
    def ready(group):
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            value=require(invoke(group['project'],'status','--group',group['group']))
            if value.get('connection_verified'):
                return value
            if value['state'] not in ('joining','starting','running','waiting_for_join'):
                raise RuntimeError(value)
            time.sleep(2)
        raise TimeoutError('联调组未在期限内完成自动加入')
    def probe(group):
        state=ready(group)
        values=[]
        for member in state['members']:
            code=("import mod.client.extraClientApi as api, clientlevel, gui\n"
                  "_result={'level':str(api.GetLevelId()),'network':str(clientlevel.get_nethernet_id()),"
                  "'screen':gui.get_top_screen(),'local':str(api.GetLocalPlayerId()),"
                  "'players':dict((str(p),api.GetEngineCompFactory().CreateName(p).GetName()) for p in api.GetPlayerList()),"
                  "'mod':api.GetSystem(%r,'ClientSystem') is not None}" % group['mod'])
            result=require(invoke(group['project'],'runtime','py','--session',member['session'],'--side','client','--code',code,read_only=True))
            assert result['state']=='completed' and result['value']['mod'], result
            values.append(result['value'])
        host=state['members'][0]['session']
        code=("import mod.server.extraServerApi as api, serverlevel\n"
              "_result={'level':str(api.GetLevelId()),'network':str(serverlevel.get_nethernet_id()),"
              "'players':dict((str(p),api.GetEngineCompFactory().CreateName(p).GetName()) for p in api.GetPlayerList()),"
              "'mod':api.GetSystem(%r,'ServerSystem') is not None}" % group['mod'])
        result=require(invoke(group['project'],'runtime','py','--session',host,'--side','server','--code',code,read_only=True))
        authority=result['value']
        assert authority['mod'] and len(authority['players'])==2, authority
        assert all(v['level']==authority['level'] and v['network']==authority['network'] and
                   v['screen']=='hud_screen' and v['players']==authority['players'] for v in values), values
        assert values[0]['local']!=values[1]['local'],values
        return {'state':state,'clients':values,'server':authority}
    try:
        for index,version in enumerate(args.engine_version):
            project=root/('project-'+str(index+1));project.mkdir()
            mod='LanProof'+str(index+1)
            require(invoke(project,'init','--name','lan-proof-'+str(index+1),'--type','addon'))
            require(invoke(project,'mod','--name',mod,'--script-dir',mod))
            started=invoke(project,'run','--new','--world-type','flat','--clients','2','--engine-version',version,'--no-gui','--detach')
            if started.get('group'):
                report['groups'].append({'project':str(project),'group':started['group'],'mod':mod})
                save()
            require(started)
        initial=[probe(g) for g in report['groups']]
        assert initial[0]['server']['network']!=initial[1]['server']['network']
        assert initial[0]['server']['level']!=initial[1]['server']['level']
        assert set(initial[0]['server']['players'].values()).isdisjoint(initial[1]['server']['players'].values())
        report['initial']=initial;save()
        first=report['groups'][0]
        old=initial[0]['state']['members'][1]['session']
        require(invoke(first['project'],'restart','--session',old))
        report['other_during_restart']=probe(report['groups'][1])
        report['after_restart']=[probe(g) for g in report['groups']]
        assert report['after_restart'][0]['state']['members'][1]['session']!=old
        report['passed']=True
    except Exception as exc:
        report['error']=str(exc)
        raise
    finally:
        for group in reversed(report['groups']):
            try:
                report['cleanup'].append(invoke(group['project'],'stop','--group',group['group']))
            except Exception as exc:
                report['cleanup'].append({'ok':False,'error':str(exc)})
        save()
    if not all(value.get('ok') for value in report['cleanup']):
        raise RuntimeError('部分测试组尚未确认退出，见 report.json')
    print(root/'report.json')


if __name__=='__main__':
    main()
