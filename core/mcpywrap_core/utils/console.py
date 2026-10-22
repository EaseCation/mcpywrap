"""Keep the caller's console encoding; escape unsupported glyphs, not Chinese."""

import sys

import click


def echo(message=None, file=None, nl=True, err=False, color=None):
    stream = file if file is not None else sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None)
    if isinstance(message, str) and encoding:
        message = message.encode(encoding, errors="backslashreplace").decode(encoding)
    return click.echo(message, file=stream, nl=nl, color=color)
