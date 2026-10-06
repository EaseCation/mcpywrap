"""Compact run view; reuses the same controller, logs and actions as mcpy ui."""
import signal
import click
from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtWidgets import QApplication
from ..mcstudio import sessions
from .session_controller import SessionController
from .log_window import SessionLogWindow


class RunSessionView(QObject):
    def __init__(self, app, project, backend, result):
        super().__init__()
        self.app = app
        self.stop_requested = False
        self.controller = SessionController(project, backend)
        self.window = SessionLogWindow(self.controller)
        self.controller.failed.connect(lambda message: click.echo(message, err=True))
        self.controller.attach(result)
        self.controller.changed.connect(self.update)
        # Keep Python signal handling responsive even when Qt has no UI events.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(100)
        app.installEventFilter(self)
        self.window.show()

    def request_stop(self, *_):
        self.stop_requested = True

    def eventFilter(self, watched, event):
        if watched is self.app and event.type() == QEvent.Type.Quit:
            if self.controller.session or self.controller.busy:
                self.request_stop()
                return True
        return super().eventFilter(watched, event)

    def update(self):
        c = self.controller
        if self.stop_requested and c.session and c.available:
            self.stop_requested = False
            c.stop()
        if not c.session and not c.busy and not c.watcher:
            self.app.quit()

    def dispose(self):
        self.app.removeEventFilter(self)
        self.timer.stop()
        self.controller.dispose()
        self.window.close()
        self.window.deleteLater()
        self.controller.deleteLater()


def show_session_window(project, backend, result):
    app = QApplication.instance() or QApplication([])
    previous_quit = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    view = RunSessionView(app, project, backend, result)
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous:
            signal.signal(sig, view.request_stop)
        click.echo('调试小窗已打开；Ctrl+C 退出游戏，或在小窗中选择“保存退出”。')
        app.exec()
        data = sessions.read(project, view.controller.data.get('session', result['session']))
        if sessions.failed_exit(project, data.get('session', result['session']), data):
            raise click.ClickException(data.get('error') or '游戏异常退出，请查看会话日志。')
        return {'session': data.get('session', result['session']), 'state': 'exited', 'backend': backend.id}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        view.dispose()
        app.setQuitOnLastWindowClosed(previous_quit)
