"""Optional live-test CLI transport; importing this module never runs a game."""
import json
import subprocess
import time


def invoke_json(command, timeout=60, history=None):
    """Resolve a macOS queued Python result by ID, without resending its source.

    UI/player commands may return a queued *transport* response before their
    game-side operation exists. Convert the completed Python value to the same
    public result shape those commands normally return on Windows.
    """
    deadline = time.monotonic() + timeout

    def invoke(arguments):
        started = time.monotonic()
        process = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                                 encoding='utf-8-sig', errors='replace',
                                 timeout=max(1, deadline - started))
        try:
            result = json.loads(process.stdout)
        except ValueError as error:
            raise RuntimeError('CLI did not return JSON: ' + process.stderr[-2000:]) from error
        if history is not None:
            history.append({'command': arguments, 'elapsed_seconds': time.monotonic()-started,
                            'exit_code': process.returncode, 'result': result})
        return result, process.returncode

    result, code = invoke(command)
    state = result.get('runtime_state', result.get('state'))
    if state not in ('queued', 'running') or not result.get('request_id'):
        return result, code
    runtime_index = command.index('runtime')
    session = command[command.index('--session') + 1]
    request_id = result['request_id']
    prefix = command[:runtime_index]
    original = result
    while state in ('queued', 'running'):
        if time.monotonic() >= deadline:
            raise TimeoutError('Python request still pending: ' + request_id + '; source was not resent')
        time.sleep(.25)
        result, code = invoke(prefix + ['runtime', 'py-result', request_id,
                                        '--session', session, '--json'])
        state = result.get('state')
    operation = command[runtime_index + 1]
    if operation in ('ui', 'player', 'install') and state == 'completed':
        value = result.get('value')
        if result.get('side') != 'client' or not isinstance(value, dict) or 'ok' not in value:
            raise RuntimeError('Queued runtime command returned an incompatible result')
        value = dict(value)
        player_install = operation == 'install' or (
            operation == 'player' and command[runtime_index + 2] == 'install')
        if player_install:
            value.update(capabilities=value.get('player_capabilities', {}), alias='mcpy.player')
        context = {key: original[key] for key in ('session', 'project', 'endpoint') if key in original}
        context.update(runtime_state='completed', request_id=request_id)
        result = dict(context, **value)
        code = 0 if result.get('ok') else 1
    return result, code
