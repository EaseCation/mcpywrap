"""Incremental logs over the same authenticated host API; no resident proxy."""
import json
import time
from urllib.parse import urlencode
import click
from .client import Client
from .profiles import project_path


def follow_logs(profile, project, params):
    client=Client(profile)
    query_options={key:params[key] for key in ('contains','since_ms','until_ms') if params.get(key) is not None}
    if query_options:
        info=client.capabilities()
        if any(key not in info.get('log_query',[]) for key in query_options):
            raise click.UsageError('App 尚不支持所请求的日志筛选，请升级 App')
    sources=['game','engine'] if params.get('source')=='all' else [params.get('source','game')]
    cursors={source:None for source in sources}
    while True:
        for source in sources:
            query={'project':project_path(profile,project),'session':params.get('session') or '',
                   'tail':params.get('tail',100),'source':source}
            query.update(query_options)
            if cursors[source] is not None:query['after']=cursors[source]
            value=client.request('GET','/logs?'+urlencode(query))
            text=value.get('text','')
            if text:
                if params.get('output_format')=='jsonl':
                    click.echo(json.dumps({'event':'log','session':value.get('session'), 'source':source,'text':text,'cursor':value['cursor']},ensure_ascii=True))
                else:click.echo(('['+source+']\n' if len(sources)>1 else '')+text,nl=False)
            cursors[source]=value['cursor']
        time.sleep(.5)
