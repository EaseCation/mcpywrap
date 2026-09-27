"""Install only the bridge payload shipped with this package, without changing trust."""
import hashlib
import json
import os
from pathlib import Path
import shutil

BINARIES = ('Injector.exe', 'Loader.dll', 'McpyMcsAuth.dll')
PAYLOAD = Path(__file__).with_name('bridge_payload')


def inspect_bridge():
    """只检查组件文件；不复制缓存、不读取身份、不改变证书信任。"""
    override = os.environ.get('MCPY_MCS_BRIDGE_DIR')
    bundled = not override and (PAYLOAD/'manifest.json').is_file()
    directory = (Path(override).expanduser().resolve() if override else PAYLOAD if bundled
                 else Path.home()/'.local/share/mcpywrap/mcs-auth-bridge')
    result = {'component_available': False, 'directory': str(directory),
              'source': 'override' if override else 'package' if bundled else 'development',
              'integrity_verified': False, 'trust_verified': False, 'login_verified': False,
              'error': None, 'hint': None}
    try:
        if bundled:
            payload_manifest()
            result['integrity_verified'] = True
        missing = [name for name in BINARIES if not (directory/name).is_file()]
        if missing:
            raise ValueError('缺少登录组件: ' + ', '.join(missing))
        result['component_available'] = True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(error=str(exc), hint='使用包含桥接组件的正式发布包；Git／可编辑安装需另行构建组件，'
                      '并通过 MCPY_MCS_BRIDGE_DIR 指定目录。组件存在不表示已登录或系统策略允许启用。')
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_manifest():
    manifest = json.loads((PAYLOAD/'manifest.json').read_text(encoding='utf-8'))
    required = set(BINARIES) | {'publisher.cer'}
    if set(manifest['files']) != required:
        raise ValueError('登录组件包不完整，请重新安装 mcpywrap。')
    for name, expected in manifest['files'].items():
        if digest(PAYLOAD/name) != expected:
            raise ValueError('登录组件校验失败，请从项目的正式发布重新安装 mcpywrap。')
    return manifest


def bridge_directory():
    override = os.environ.get('MCPY_MCS_BRIDGE_DIR')
    if override:
        directory = Path(override).expanduser().resolve()
    elif (PAYLOAD/'manifest.json').is_file():
        manifest = payload_manifest()
        version = digest(PAYLOAD/'manifest.json')[:16]
        directory = Path.home()/'.local/share/mcpywrap/mcs-auth-bridge'/version
        directory.mkdir(parents=True, exist_ok=True)
        for name, expected in manifest['files'].items():
            target = directory/name
            if not target.is_file():
                temporary = target.with_suffix(target.suffix+'.tmp')
                shutil.copyfile(PAYLOAD/name, temporary)
                os.replace(temporary, target)
            if digest(target) != expected:
                raise ValueError('本机登录组件已被更改，请删除组件缓存后重新运行。')
    else:
        directory = Path.home()/'.local/share/mcpywrap/mcs-auth-bridge'
    if not all((directory/name).is_file() for name in BINARIES):
        raise ValueError('此安装缺少登录组件，请重新安装正式版；源码开发者可运行 scripts/build_mcs_auth_bridge.py。')
    return directory


def trusted_certificate_candidate(directory):
    """Never offer to trust certificates supplied by an arbitrary developer override."""
    try:
        manifest = payload_manifest()
        if any(digest(directory/name) != expected for name, expected in manifest['files'].items()):
            return None
        return {'path': str(directory/'publisher.cer'), 'thumbprint': manifest['thumbprint'],
                'subject': manifest['subject'], 'expires': manifest['expires']}
    except (OSError, ValueError, KeyError):
        return None
