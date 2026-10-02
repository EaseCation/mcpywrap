"""Public recording commands, with explicit group routing to avoid session-name collisions."""
import click

from ..command_context import OperationCommand, project_dir, remote_url
from ..mcstudio import recordings
from ..recording_io import output_path, transfer, frame_result


class RecordingCommand(OperationCommand):
    def invoke(self, ctx):
        ctx.params.pop('json_output', None)
        if remote_url():
            from ..remote.client import routed_recording
            return routed_recording(ctx.info_name, ctx.params)
        return click.Command.invoke(self, ctx)


@click.group(name='record')
def record_cmd():
    """Record a session while sending inputs, download MP4, and extract PNG frames."""


@record_cmd.command(cls=RecordingCommand, name='start')
@click.option('--session', required=True)
@click.option('--duration', type=click.IntRange(1, 300), default=10, show_default=True)
@click.option('--fps', type=click.IntRange(1, 60), default=30, show_default=True)
@click.option('--request-id', help='32 lowercase hex characters; reuse to recover the same request')
def start_cmd(session, duration, fps, request_id):
    """Return after the first frame is written; recording continues independently."""
    return recordings.start(project_dir(), session, duration, fps, request_id)


@record_cmd.command(cls=RecordingCommand, name='status')
@click.option('--session', required=True)
@click.option('--recording')
@click.option('--list', 'list_recordings', is_flag=True)
def status_cmd(session, recording, list_recordings):
    """Query a recording or list this session's jobs, including after game exit."""
    if bool(recording) == list_recordings:
        raise click.UsageError('Specify --recording or --list')
    return recordings.status(project_dir(), session, recording)


@record_cmd.command(cls=RecordingCommand, name='stop')
@click.option('--session', required=True)
@click.option('--recording', required=True)
def stop_cmd(session, recording):
    """Finalize an early clip; leave the game running."""
    return recordings.stop(project_dir(), session, recording)


@record_cmd.command(cls=RecordingCommand, name='delete')
@click.option('--session', required=True)
@click.option('--recording', required=True)
def delete_cmd(session, recording):
    """Delete finished execution-side artifacts; keep downloaded copies."""
    return recordings.delete(project_dir(), session, recording)


@record_cmd.command(cls=RecordingCommand, name='download')
@click.option('--session', required=True)
@click.option('--recording', required=True)
@click.option('--output', required=True, help='Nonexistent caller-side .mp4 path')
def download_cmd(session, recording, output):
    """Copy in 1 MiB chunks, verify length/hash, and publish without overwriting."""
    output = output_path(output)
    with recordings.artifact(project_dir(), session, recording) as (video, data):
        with video.open('rb') as stream:
            transfer(stream, output, data['size'], data['sha256'])
    return {**data, 'video': str(output)}


@record_cmd.command(cls=RecordingCommand, name='frames')
@click.option('--session', required=True)
@click.option('--recording', required=True)
@click.option('--frame', 'frames', type=click.IntRange(0), multiple=True, help='Zero-based encoded frame index; repeatable')
@click.option('--at', 'times', type=click.FloatRange(0), multiple=True, help='Seconds; floor(time * fps); repeatable')
@click.option('--output', required=True, help='Nonexistent caller-side directory for PNG and manifest')
def frames_cmd(session, recording, frames, times, output):
    """Extract up to 100 encoded frames; frame/time selectors are mutually exclusive."""
    output = output_path(output, directory=True)
    with recordings.frames_archive(project_dir(), session, recording, frames, times) as (archive, info):
        with archive.open('rb') as stream:
            transfer(stream, output, info['size'], info['sha256'], publish=False)
    return frame_result(output)
