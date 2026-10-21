# coding: utf-8
"""Shared plan compilation for Windows input and injected Python 2 game actions."""


def compile_timeline(steps, durations, limit_ms):
    """Omitted at_ms follows the previous planned end; no implicit step gap."""
    if len(steps) != len(durations):
        raise ValueError('timeline duration count mismatch')
    result, cursor = [], 0
    for step, duration in zip(steps, durations):
        if type(duration) is not int or duration < 0:
            raise ValueError('duration must be a nonnegative integer')
        if 'at_ms' in step and 'delay_ms' in step:
            raise ValueError('at_ms and delay_ms are mutually exclusive within a step')
        delay = step.get('delay_ms', 0)
        if type(delay) is not int or not 0 <= delay <= 10000:
            raise ValueError('delay_ms must be an integer from 0 to 10000')
        at = step.get('at_ms', cursor + delay)
        if type(at) is not int or at < cursor or at + duration > limit_ms:
            raise ValueError('at_ms must follow the previous planned end and fit the timeline limit')
        item = dict(step)
        item.pop('delay_ms', None)
        item['at_ms'] = at
        result.append(item)
        cursor = at + duration
    return result
