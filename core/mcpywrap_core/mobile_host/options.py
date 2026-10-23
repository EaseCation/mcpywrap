"""Contextual help uses workspace binding, never the CLI process's operating system."""
import click
from . import profiles


def bound_context(ctx):
    from ..command_context import _context, project_dir
    state=_context.get()
    if state is not None and state.local: return False
    profile=profiles.select(project_dir())
    return profile is not None and not (state and state.remote and state.remote.rstrip('/')!=profile['endpoint'])


class HostOption(click.Option):
    def get_help_record(self,ctx):
        return super().get_help_record(ctx) if bound_context(ctx) else None


class LogSource(click.Choice):
    def __init__(self):
        super().__init__(['game','engine','worker','client','server','all'])

    def target_type(self,ctx):
        return click.Choice(['game','engine','client','server','all'] if bound_context(ctx) else ['game','engine','worker','all'])

    def get_metavar(self,param,ctx):
        return self.target_type(ctx).get_metavar(param,ctx)

    def convert(self,value,param,ctx):
        return self.target_type(ctx).convert(value,param,ctx)
