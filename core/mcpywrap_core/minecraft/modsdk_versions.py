"""补全库版本目录：可离线读取，网络子进程有整体截止时间。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def cache_path():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'mcpywrap/modsdk-versions.json'


def catalog(offline=False, refresh=False):
    path=cache_path()
    try:
        cached=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(cached.get('versions'),list) or not all(isinstance(v,str) for v in cached['versions']):
            cached=None
    except (OSError,ValueError):cached=None
    if cached and (offline or not refresh):
        return dict(cached,cached=True,stale=time.time()-cached.get('fetched_at',0)>86400)
    if offline:
        return {'versions':[],'cached':False,'network_required':True,'hint':'尚无缓存；联网后运行 mcpy modsdk --list --refresh'}
    worker="""import json,urllib.request
with urllib.request.urlopen('https://pypi.org/pypi/mc-netease-sdk/json',timeout=5) as response:
 data=response.read(8*1024*1024+1)
 if len(data)>8*1024*1024:raise ValueError('SDK metadata exceeds limit')
 value=json.loads(data)
 versions=sorted(value['releases'],key=lambda v:value['releases'][v][0].get('upload_time_iso_8601','') if value['releases'][v] else '')
 print(json.dumps(versions))
"""
    try:
        result=subprocess.run([sys.executable,'-c',worker],capture_output=True,text=True,timeout=12,check=True)
        versions=json.loads(result.stdout)
        if not isinstance(versions,list) or not all(isinstance(v,str) for v in versions):raise ValueError('Invalid versions')
        value={'versions':versions,'fetched_at':time.time()}
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.versions-',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream)
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
        return dict(value,cached=False,stale=False)
    except (OSError,ValueError,subprocess.SubprocessError):
        if cached:return dict(cached,cached=True,stale=True,warning='联网刷新失败，返回上次缓存')
        return {'versions':[],'cached':False,'network_required':True,'hint':'在 12 秒内未取得版本目录，请检查网络；查询不会安装依赖'}
