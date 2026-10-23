"""HTTP operations. A dropped connection never retries a mutation or executes locally."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from ..remote.client import NoRedirect, bounded_response
from ..remote.protocol import RemoteError
from . import PROTOCOL
from . import profiles
from .intervention import require_user


class Client:
    def __init__(self, profile):
        self.profile = profile
        self.endpoint = profiles.endpoint(profile['endpoint'])
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, data=None, authenticated=True, binary=False):
        headers = {'Accept': 'application/octet-stream' if binary else 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer '+self.profile['token']
        if data is not None: headers['Content-Type'] = 'application/json'
        request = Request(self.endpoint+'/v2'+path, None if data is None else json.dumps(data, ensure_ascii=True, allow_nan=False).encode(), headers, method=method)
        try:
            try: response = self.opener.open(request, timeout=30)
            except HTTPError as error: response = error
            with response:
                raw = bounded_response(response)
                if binary and response.status == 200: return raw
                try: result = json.loads(raw)
                except (UnicodeError, ValueError): raise RemoteError('宿主返回格式不兼容', 'invalid_response') from None
                if not isinstance(result, dict): raise RemoteError('宿主返回格式不兼容', 'invalid_response')
                if response.status >= 400 or result.get('ok') is False:
                    error = RemoteError(result.get('error', '宿主操作失败'), result.get('code', 'host_error'), response.status, result.get('hint'))
                    error.details = result.get('details', {})
                    require_user(error)
                    raise error
                return result
        except (URLError, TimeoutError, OSError) as error:
            if isinstance(error, RemoteError): raise
            failure = RemoteError('无法连接 mcpy App；连接失败不足以区分服务关闭、进程退出或端口错误', 'host_unavailable',
                                  hint='打开 mcpy://service/start 恢复开发连接；主动暂停的服务需在开发工具页重新开启。已提交的操作先查询原任务。')
            failure.details = {'endpoint': self.endpoint, 'recovery_uri': 'mcpy://service/start',
                               'last_known_service': profiles.cached_service(self.profile), 'live_state': 'unavailable'}
            require_user(failure)
            raise failure from error

    def normalize(self, result):
        result=dict(result)
        for key in ('output','artifact','log','script_log','script_state'):
            value=result.get(key)
            if isinstance(value,str):
                for prefix in ('/sdcard/mcpy/','/storage/emulated/0/mcpy/'):
                    if value.startswith(prefix): result[key]=str(Path(self.profile['workspace'])/value[len(prefix):])
        return result

    def capabilities(self):
        result = self.request('GET', '/capabilities')
        if result.get('protocol_version') != PROTOCOL or result.get('installation_id') != self.profile['installation_id']:
            raise RemoteError('宿主身份或协议已变化，请重新配对', 'host_identity_changed')
        profiles.observe_service(self.profile, result)
        return result

    def operation(self, operation, project, parameters):
        info = self.capabilities()
        if operation not in info.get('operations', []):
            raise RemoteError('宿主未提供能力：'+operation, 'capability_missing')
        if operation=='logs':
            requested=[key for key in ('contains','summary','since_ms','until_ms') if parameters.get(key) is not None and parameters.get(key) is not False]
            if any(key not in info.get('log_query',[]) for key in requested):
                raise RemoteError('App 尚不支持所请求的日志筛选，请升级 App', 'capability_missing')
        if parameters.get('launch_timeout') is not None and not info.get('launch_options',{}).get('ack_timeout'):
            raise RemoteError('当前宿主不支持设置启动确认等待时间', 'capability_missing')
        identity = uuid.uuid4().hex
        request = {'request_id': identity, 'operation': operation,
                   'project': profiles.project_path(self.profile, project), 'parameters': parameters,
                   'preparation_client': True}
        # The ID is defined by v2 and can be queried even if the POST response is lost.
        job_id = hashlib.sha256((self.profile['client_id']+':'+identity).encode()).hexdigest()
        from .receipts import Receipts
        Receipts(self.profile).submitted(job_id, request)
        try:
            response = self.request('POST', '/operations', request)
            if response.get('operation_id') != job_id:
                raise RemoteError('宿主返回了不同的操作 ID', 'invalid_response')
        except RemoteError as error:
            self.recovery_hint(error, job_id, identity)
            raise
        return self.wait(job_id, info)

    def recovery_hint(self, error, job_id, request_id=None):
        if require_user(error,job_id):
            return
        error.hint = ((getattr(error, 'hint', None) or '') +
                      ' 操作 ID：'+job_id+'；使用 mcpy host resume --operation '+job_id+
                      ' 查询原任务及关联会话的新证据；不会重新提交或重放操作。'+
                      (' 请求 ID：'+request_id if request_id else ''))

    def resume(self, job_id):
        import re
        if not re.fullmatch(r'[0-9a-f]{64}', job_id):
            raise ValueError('无效操作 ID')
        try:
            return self.wait(job_id, self.capabilities(), reconcile=True)
        except RemoteError as error:
            self.recovery_hint(error,job_id)
            raise

    def wait(self, job_id, info, reconcile=False):
        from .preparation import LocalPreparation
        from .receipts import Receipts
        checked_at = 0.0
        def cancelled():
            nonlocal checked_at
            if time.monotonic()-checked_at < 1: return False
            checked_at = time.monotonic()
            try:
                return self.request('GET', '/operations/'+job_id)['state'] in ('cancelled','interrupted','failed','unknown')
            except RemoteError as error:
                # Only confirmed cancellation/revocation stops the caller's finite script.
                # Connection loss alone is not permission to replay or discard its result.
                return error.code == 'unauthorized'
        preparation = LocalPreparation(self.profile, info['core_version'], cancel=cancelled)
        receipts = Receipts(self.profile)
        completed = set()
        try:
            while True:
                job = self.request('GET', '/operations/'+job_id)
                receipts.observed(job_id, job)
                state = job['state']
                if state == 'completed': return dict(self.normalize(job['result']), operation_id=job_id, execution='host', endpoint=self.endpoint)
                if state in ('failed', 'interrupted', 'cancelled', 'unknown', 'waiting_user'):
                    observation = job.get('observation') or {}
                    if reconcile and state == 'unknown' and observation.get('process_alive') is True and observation.get('pid',0)>0 and observation.get('state') in ('loading','running') and (not observation.get('pipRequested') or observation.get('pip')):
                        return dict(self.normalize(observation), ok=True, operation_id=job_id, execution='host',
                                    endpoint=self.endpoint, reconciled=True, original_operation_state=state)

                    error=RemoteError(job.get('error') or '宿主任务未完成', job.get('code', state),
                                      hint=job.get('hint') or ('操作 ID：'+job_id+'；不会自动重试'))
                    error.details=dict(job.get('result') or {}, operation_state=state, operation_id=job_id, execution='host', endpoint=self.endpoint)
                    if observation:
                        error.details['observation']=observation
                        if state != 'waiting_user':
                            error.hint=observation.get('hint') or error.hint
                    raise error
                step = job.get('preparation')
                if step and step['id'] not in completed:
                    result = receipts.execute(job_id, step, preparation.execute)
                    self.request('POST', '/operations/'+job_id+'/preparation/'+step['id'], result)
                    completed.add(step['id'])
                time.sleep(.3)
        except KeyboardInterrupt:
            # Cancellation is best effort; do not hide the identity if the connection is gone.
            import sys
            print('中断等待；原任务 ID：'+job_id, file=sys.stderr)
            try: self.request('POST', '/operations/'+job_id+'/cancel', {})
            except RemoteError: pass
            raise
        except RemoteError as error:
            self.recovery_hint(error, job_id)
            raise


def pair(url, code, workspace, label='mcpy CLI', timeout=900):
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir(): raise ValueError('请先挂载 App 的 mcpy 公共工作目录')
    client = Client({'endpoint': url})
    info = client.request('GET', '/capabilities', authenticated=False)
    resumable = info.get('pairing', {}).get('resume') is True
    key = hashlib.sha256(json.dumps([url, code, str(workspace), label]).encode()).hexdigest()
    receipt = profiles.location().parent / ('pairing-'+key+'.json')
    saved = json.loads(receipt.read_text()) if resumable and receipt.exists() else {}
    if saved and time.time() > saved.get('expires', 0):
        receipt.unlink(missing_ok=True)
        raise ValueError('连接请求已过期，请在 App 重新复制连接提示词')
    if not saved:
        saved = {'request_id': uuid.uuid4().hex, 'expires': time.time()+900}
        if resumable: profiles.write_private(receipt, saved)

    def request(path, data):
        # 新宿主保证配对开始、验证和查询幂等；旧宿主不重放开始请求。
        for attempt in range(3 if resumable else 1):
            try:
                return client.request('POST', path, data, authenticated=False)
            except RemoteError as error:
                if error.code != 'host_unavailable' or attempt == (2 if resumable else 0):
                    if resumable:
                        error.hint = (error.hint or '')+' 修复连接后重试同一条配对命令，会继续原请求。'
                    raise
                time.sleep(1)

    if 'pending' not in saved:
        data = {'code': code, 'label': label}
        if resumable: data['request_id'] = saved['request_id']
        saved['pending'] = request('/pairings', data)
        saved['expires'] = saved['pending'].get('expires_at', (time.time()+900)*1000)/1000
        if resumable: profiles.write_private(receipt, saved)
    pending = saved['pending']
    base = '/pairings/'+pending['id']
    credentials = {'secret': pending['secret']}
    result = request(base+'/result', credentials)
    if result['state'] == 'verifying':
        probe = (workspace/pending['probe']).resolve()
        if workspace not in probe.parents: raise ValueError('无效的共享目录验证请求')
        try:
            proof = hashlib.sha256(probe.read_bytes()).hexdigest()
            probe.with_suffix('.response').write_text(pending['challenge'], encoding='utf-8')
        except OSError as error:
            raise RemoteError('无法读写共享作品目录', 'workspace_unavailable',
                              hint='检查开发工具的目录挂载和所有文件访问权限，然后重试同一条配对命令。') from error
        request(base+'/verify', dict(credentials, proof=proof))
        saved['expires'] = time.time()+900
        if resumable: profiles.write_private(receipt, saved)
    import sys
    print('等待你允许连接：可直接点击 mcpy 弹出的确认卡或通知中的「允许连接」。没有提示时再打开 mcpy 的 开发工具页。', file=sys.stderr)
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        result = request(base+'/result', credentials)
        if result['state'] == 'approved':
            profiles.bind({'endpoint': url, 'workspace': str(workspace), 'installation_id': result['installation_id'],
                           'client_id': result['client_id'], 'token': result['token']})
            receipt.unlink(missing_ok=True)
            return {'paired': True, 'workspace': str(workspace), 'endpoint': url, 'client_id': result['client_id']}
        if result['state'] in ('denied','expired'):
            receipt.unlink(missing_ok=True)
            raise ValueError('连接已被拒绝' if result['state']=='denied' else '连接请求已过期，请重新复制连接提示词')
        time.sleep(.5)
    raise ValueError('还没有收到连接确认；确认后重试同一条配对命令即可继续')
