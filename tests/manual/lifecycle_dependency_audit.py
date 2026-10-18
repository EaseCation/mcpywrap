"""Windows real-engine dependency transitions, using only the public CLI for operations.

Creates a fresh disposable project and a private game profile under --output.
Keeps worlds, command responses and timings; stops only sessions in that project.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--engine-version')
    parser.add_argument('--mcs-download-path')
    parser.add_argument('--profile', type=Path, help='Reuse an existing isolated test profile; never use a personal profile')
    parser.add_argument('--ready-timeout', type=float, default=180)
    parser.add_argument('--with-hook', action='store_true', help='Also verify generated code from before_run')
    parser.add_argument('--resume-instance', help='Retry the first stage in this script\'s existing fixture world')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This acceptance run requires the Windows engine.')
    root = args.output.resolve()
    if args.resume_instance:
        if not (root/'commands.json').is_file() or not (root/'project/behavior_pack/AuditMain/modMain.py').is_file():
            parser.error('--resume-instance requires a fixture previously created by this script')
        evidence = root/('attempt-'+uuid.uuid4().hex[:8])
        evidence.mkdir()
    else:
        root.mkdir(parents=True, exist_ok=False)
        evidence = root
    project = root/'project'
    # Preserve an explicitly supplied alias: this engine derives Python module
    # names from the lexical depth of its Windows data path.
    profile = args.profile.absolute() if args.profile else root/'profile'
    if args.profile:
        if not profile.is_dir():
            parser.error('--profile must be an existing isolated test directory')
    else:
        profile.mkdir(exist_ok=bool(args.resume_instance))
    profile_alias = None
    # The Windows 3.10 loader strips ten absolute path components before
    # importing modMain. Match a normal C:/Users/<user>/AppData/Roaming depth
    # without moving the fixture's data or borrowing a personal game profile.
    if len((profile/'AppData/Roaming').parts) != 5:
        if not profile.drive.endswith(':'):
            parser.error('This engine acceptance fixture requires a local Windows drive.')
        from mcpywrap.mcstudio.symlinks import _create_directory_link
        alias_parent = Path(tempfile.mkdtemp(prefix='.mcpy-audit-', dir=profile.anchor))
        alias = alias_parent/'profile'
        try:
            _create_directory_link(str(profile), str(alias))
        except BaseException:
            alias_parent.rmdir()
            raise
        profile_alias = (alias, profile.resolve())
        profile = alias
    (evidence/'profile.json').write_text(json.dumps({'path': str(profile), 'data': str(profile.resolve())},
                                                   indent=2), encoding='utf-8')
    # MC Studio preflight expects an initialized user data root. This empty,
    # private equivalent contains no account, world or globally installed pack.
    (profile/'AppData/Roaming/MinecraftPE_Netease/games/com.netease').mkdir(parents=True, exist_ok=True)
    (profile/'AppData/Local').mkdir(parents=True, exist_ok=True)
    options = profile/'AppData/Roaming/MinecraftPE_Netease/minecraftpe/options.txt'
    if not options.exists():
        options.parent.mkdir(parents=True, exist_ok=True)
        options.write_text('gfx_renderengine:0\ngfx_max_framerate:30\ngfx_viewdistance:64\n'
                           'gfx_fullscreen:0\nhas_dismissed_new_player_flow:1\n', encoding='utf-8')
    env = dict(os.environ, USERPROFILE=str(profile), APPDATA=str(profile/'AppData/Roaming'),
               LOCALAPPDATA=str(profile/'AppData/Local'), PYTHONIOENCODING='utf-8')
    repo = Path(__file__).resolve().parents[2]
    env['PYTHONPATH'] = str(repo)
    sequence = []

    def call(label, *command, expect=True):
        started = time.monotonic()
        completed = subprocess.run([sys.executable, '-m', 'mcpywrap', '--local', '--project', str(project),
                                    '--non-interactive', *command, '--json'], cwd=repo, env=env,
                                   capture_output=True, text=True, encoding='utf-8', timeout=360)
        (evidence/(label + '.stdout')).write_text(completed.stdout, encoding='utf-8')
        (evidence/(label + '.stderr')).write_text(completed.stderr, encoding='utf-8')
        result = json.loads(completed.stdout)
        sequence.append(dict(label=label, exit_code=completed.returncode,
                             seconds=round(time.monotonic()-started, 3), result=result))
        (evidence/'commands.json').write_text(json.dumps(sequence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(label, completed.returncode, result.get('state'), result.get('code'), flush=True)
        if expect:
            assert completed.returncode == 0 and result.get('ok'), result
        return result

    def addon(path, name):
        path.mkdir()
        for kind, module in (('behavior', 'data'), ('resource', 'resources')):
            pack = path/(kind+'_pack')
            pack.mkdir()
            (pack/'manifest.json').write_text(json.dumps(dict(format_version=2, header=dict(
                name=name, description='Disposable lifecycle audit', uuid=str(uuid.uuid4()),
                version=[1, 0, 0], min_engine_version=[1, 18, 0]), modules=[dict(
                    type=module, uuid=str(uuid.uuid4()), version=[1, 0, 0])])), encoding='utf-8')
        (path/'pyproject.toml').write_text('[project]\nname="'+name+'"\nversion="0.1.0"\n'
                                          'dependencies=[]\n[tool.mcpywrap]\nproject_type="addon"\n', encoding='utf-8')

    def deployment():
        records = list((project/'.runtime/deployments').glob('*.json'))
        records = [p for p in records if not p.name.endswith('.transaction.json')]
        assert len(records) == 1, records
        return json.loads(records[0].read_text(encoding='utf-8'))

    def start(label, *options):
        command = ['run', '--detach', '--no-gui', *options]
        for key in ('engine_version', 'mcs_download_path'):
            if getattr(args, key):
                command += ['--'+key.replace('_', '-'), getattr(args, key)]
        result = call(label, *command)
        deadline = time.monotonic()+args.ready_timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            state = call(label+'-ready-'+str(attempt), 'status', '--session', result['session'])
            if state.get('world_ready'):
                return result
            assert state['state'] in ('starting', 'running'), state
            time.sleep(1)
        raise AssertionError('World readiness deadline: ' + label)

    def verify(label, session, expected):
        for side in ('client', 'server'):
            result = call(label+'-'+side, 'runtime', 'py', '--session', session, '--side', side,
                          '--code', "import sys\n_result = dict((name, getattr(module, 'STATES', {})) "
                          "for name, module in sys.modules.items() if name.endswith('AuditMain.modMain'))")
            assert any(states.get(side) == expected for states in result['value'].values()), result
            if args.with_hook:
                generated = call(label+'-generated-'+side, 'runtime', 'py', '--session', session, '--side', side,
                    '--code', "import sys\n_result = [getattr(module, 'GENERATED', {}) "
                    "for name, module in sys.modules.items() if name.endswith('AuditMain.modMain')]")
                assert any(states.get(side) == 'hook-generated' for states in generated['value']), generated
        call(label+'-logs', 'logs', '--session', session, '--tail', '150')

    def stop(label, session):
        result = call(label, 'stop', '--session', session)
        assert result['state'] == 'exited', result

    if not args.resume_instance:
        addon(project, 'lifecycle-audit')
        addon(root/'common', 'audit-common')
    module = project/'behavior_pack/AuditMain'
    module.mkdir(exist_ok=bool(args.resume_instance))
    (module/'__init__.py').write_text('', encoding='utf-8')
    (module/'modMain.py').write_text('''from mod.common.mod import Mod
STATES = {}
GENERATED = {}
def record(side):
    try:
        from AuditDependency import VALUE
    except ImportError:
        VALUE = 'absent'
    STATES[side] = VALUE
    try:
        from AuditGenerated import VALUE as generated
        GENERATED[side] = generated
    except ImportError:
        pass
    print('[LifecycleAudit] ' + side + '=' + VALUE)
@Mod.Binding(name='LifecycleAudit', version='1.0.0')
class Audit:
    @Mod.InitClient()
    def client(self):
        record('client')
    @Mod.InitServer()
    def server(self):
        record('server')
''', encoding='utf-8')
    (root/'common/behavior_pack/AuditDependency.py').write_text("VALUE = 'dependency-present'\n", encoding='utf-8')
    if args.with_hook:
        from mcpywrap.dependencies import read_project, write_project
        tools = project/'tools'
        tools.mkdir(exist_ok=True)
        (tools/'generate.py').write_text("""from pathlib import Path
root = Path('.')
count = root/'.mcpy/hook-count'
count.parent.mkdir(exist_ok=True)
count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')
if (root/'.mcpy/fail-hook').exists():
    raise SystemExit(7)
(root/'behavior_pack/AuditGenerated.py').write_text("VALUE = 'hook-generated'\\n", encoding='utf-8')
""", encoding='utf-8')
        config = read_project(project)
        config['tool']['mcpywrap'].update(scripts={'generate': {'python': 'tools/generate.py', 'timeout': 30}},
                                          hooks={'before_run': ['generate']})
        write_project(project, config)
    try:
        call('capabilities', 'doctor', '--capabilities')
        first = (start('zero', args.resume_instance) if args.resume_instance else
                 start('zero', '--new', '--world-type', 'flat', '--world-name', 'Dependency Lifecycle Audit'))
        world = first['instance']
        verify('zero-loaded', first['session'], 'absent')
        initial = deployment()
        initial_config = json.loads(Path(first['config_path']).read_text(encoding='utf-8'))
        call('add', 'add', '--path', '../common')
        count_before = (project/'.mcpy/hook-count').read_bytes() if args.with_hook else None
        reused = call('reuse-while-changed', 'run', world, '--no-gui', '--detach')
        assert reused['session'] == first['session'] and reused['source_matches'] is False
        if args.with_hook:
            assert (project/'.mcpy/hook-count').read_bytes() == count_before
        assert deployment() == initial
        blocked = call('new-while-changed', 'run', '--new', '--no-gui', '--detach', expect=False)
        assert blocked.get('ok') is False and blocked.get('code') == 'deployment_in_use', blocked
        assert deployment() == initial
        stop('stop-zero', first['session'])
        second = start('one', world)
        verify('one-loaded', second['session'], 'dependency-present')
        one = deployment()
        assert one['path'] == initial['path']
        peer = start('same-version-second-world', '--new', '--world-type', 'flat')
        verify('peer-loaded', peer['session'], 'dependency-present')
        assert peer['instance'] != world and deployment() == one
        call('remove', 'remove', '--path', '../common')
        blocked = call('new-after-removal-while-running', 'run', '--new', '--no-gui', '--detach', expect=False)
        assert blocked.get('ok') is False and blocked.get('code') == 'deployment_in_use', blocked
        assert deployment() == one
        verify('active-still-old-version', second['session'], 'dependency-present')
        stop('stop-peer', peer['session'])
        stop('stop-one', second['session'])
        third = start('zero-again', world)
        verify('zero-again-loaded', third['session'], 'absent')
        final = deployment()
        assert final['path'] == initial['path']
        assert not (Path(final['path'])/'behavior_pack/AuditDependency.py').exists()
        final_config = json.loads(Path(third['config_path']).read_text(encoding='utf-8'))
        for kind in ('behavior_packs', 'resource_packs'):
            assert initial_config['world_info'][kind] == final_config['world_info'][kind]
        stop('stop-zero-again', third['session'])
        if args.with_hook:
            failure = project/'.mcpy/fail-hook'
            failure.touch()
            rejected = call('failed-hook', 'run', world, '--no-gui', '--detach', expect=False)
            assert rejected.get('code') == 'script_failed' and rejected.get('script_exit_code') == 7, rejected
            assert deployment() == final
            failed = call('failed-hook-state', 'status', '--session', rejected['session'])
            assert failed['state'] == 'failed' and not failed.get('game'), failed
            failure.unlink()
        repeat = start('unchanged-restart', world)
        assert deployment() == final
        verify('unchanged-loaded', repeat['session'], 'absent')
        stop('stop-unchanged', repeat['session'])
        (evidence/'result.json').write_text(json.dumps(dict(ok=True, world=world,
            generated_hook_verified=args.with_hook,
            deployment_path=final['path'], cases=['0-to-1-to-0', 'unchanged-restart', 'same-world-reuse',
            'active-reader-rejection', 'two-independent-worlds', 'old-module-absent', 'stable-global-links']), indent=2), encoding='utf-8')
    finally:
        # Failed starts may return their session only inside error details.
        # This brand-new project belongs exclusively to this acceptance run.
        current = call('cleanup-status', 'status', '--list')
        for item in current['sessions']:
            if item['state'] in ('starting', 'running', 'failed'):
                stop('cleanup-'+item['session'], item['session'])
        if profile_alias:
            alias, expected = profile_alias
            from mcpywrap.mcstudio.deployment_links import is_link, unlink
            if not is_link(alias) or alias.resolve() != expected:
                raise RuntimeError('Test profile alias changed externally; preserved for inspection: ' + str(alias))
            unlink(alias)
            alias.parent.rmdir()


if __name__ == '__main__':
    main()
