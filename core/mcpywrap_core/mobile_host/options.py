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

    def get_metavar(self,param,ctx=None):
        # Click 8.0/8.1 calls this without ctx; 8.2+ passes it explicitly.
        target=self.target_type(ctx)
        import inspect
        if 'ctx' in inspect.signature(target.get_metavar).parameters:
            return target.get_metavar(param,ctx=ctx)
        return target.get_metavar(param)

    def convert(self,value,param,ctx):
        return self.target_type(ctx).convert(value,param,ctx)
