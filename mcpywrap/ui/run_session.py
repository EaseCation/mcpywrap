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
        self.detaching = False
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
        if watched is self.window and event.type() == QEvent.Type.Close:
            self.detaching = True
        if watched is self.app and event.type() == QEvent.Type.Quit:
            if self.controller.busy or self.controller.watcher:
                self.detaching = True
                return True
        return super().eventFilter(watched, event)

    def update(self):
        c = self.controller
        if self.detaching:
            if c.watcher and c.available:
                c.set_watching(False)
            if not c.busy and not c.watcher:
                self.app.quit()
            return
        if self.stop_requested and c.session and c.available:
            self.stop_requested = False
            if c.group:
                c.interrupt_group()
                self.detaching = True
            elif c.owns_session:
                c.stop()
            else:
                self.detaching = True
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
        click.echo('调试小窗已打开；关闭面板保留游戏。停止游戏请使用对应操作。')
        app.exec()
        data = sessions.read(project, view.controller.data.get('session', result['session']))
        if sessions.failed_exit(project, data.get('session', result['session']), data):
            raise click.ClickException(data.get('error') or '游戏异常退出，请查看会话日志。')
        return dict(result, session=data.get('session', result['session']), state=data['state'], backend=backend.id)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        view.dispose()
        app.setQuitOnLastWindowClosed(previous_quit)
