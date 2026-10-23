"""Literal log selection, without inferring application health from messages."""
from collections import Counter

HISTORY_BYTES = 512 * 1024


def select(text, *, contains=None, tail=100, summary=False):
    lines = text.splitlines(keepends=True)
    matched = [line for line in lines if contains is None or contains in line]
    result = {'text': ''.join(matched[-tail:]) if tail else '',
              'scanned_lines': len(lines), 'matched_lines': len(matched)}
    if summary:
        counts = Counter(line.rstrip('\r\n') for line in matched if line.strip())
        result['summary_truncated']=len(counts)>tail
        result['unique_messages']=len(counts)
        result['summary'] = [{'text': text, 'count': count} for text, count in
                             sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:tail]]
    return result


def snapshot(path, **options):
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size-HISTORY_BYTES)
            stream.seek(start)
            raw = stream.read(HISTORY_BYTES)
        if start:
            raw = raw.partition(b'\n')[2]  # A partial first line is not evidence.
        result = select(raw.decode('utf-8', errors='replace'), **options)
        return dict(result, available=True, scan_truncated=start > 0, scan_limit_bytes=HISTORY_BYTES)
    except FileNotFoundError:
        return dict(select('', **options), available=False, scan_truncated=False, scan_limit_bytes=HISTORY_BYTES)


class StreamFilter:
    """Preserve split writes until a complete line is available for literal matching."""
    def __init__(self, contains):
        self.contains = contains
        self.pending = ''

    def feed(self, text, final=False):
        if self.contains is None:
            return text
        self.pending += text
        lines = self.pending.splitlines(keepends=True)
        self.pending = ''
        if lines and not lines[-1].endswith(('\n', '\r')) and not final:
            self.pending = lines.pop()
        # Limit a malformed writer's unterminated line; explicitly signal data loss.
        if len(self.pending) > HISTORY_BYTES:
            raise ValueError('日志单行超过 512 KiB；请直接检查原日志文件')
        return ''.join(line for line in lines if self.contains in line)


def show_snapshot(result, summary=False):
    """Render host and local snapshots with the same bounded-evidence wording."""
    import click
    streams=result.get('streams')
    if isinstance(streams,dict): streams=list(streams.values())
    if not isinstance(streams,list): streams=[result]
    for item in streams:
        if len(streams)>1: click.echo('['+item.get('session','')+' '+item.get('source','')+']')
        if not item.get('available',True):
            click.echo('此来源尚无日志。');continue
        if item.get('scan_truncated'): click.echo('仅扫描最近 512 KiB，统计不代表完整日志。',err=True)
        if item.get('scan_scope'): click.echo('筛选范围：远端最近 10000 行。',err=True)
        if summary:
            for row in item.get('summary',[]):
                side=('['+row['side']+'] ') if row.get('side') else ''
                click.echo(str(row['count'])+' × '+side+row['text'])
            if item.get('summary_truncated'): click.echo('仅显示部分消息分组；完整匹配数量见 JSON 结果。',err=True)
        else: click.echo(item.get('text',''),nl=False)
        if item.get('matched_lines')==0: click.echo('本次扫描范围内未找到匹配日志。')
