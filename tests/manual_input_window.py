"""Own inert Qt window for native keyboard/mouse receipt timing; no game or other app input."""
import argparse
import json
import os
from pathlib import Path
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    events = []

    class Receiver(QWidget):
        def record(self, kind, value):
            events.append({'type': kind, 'value': value, 'received_ns': time.perf_counter_ns()})

        def keyPressEvent(self, event):
            self.record('key_down', event.key())

        def keyReleaseEvent(self, event):
            self.record('key_up', event.key())

        def mousePressEvent(self, event):
            self.record('mouse_down', int(event.button()))

        def mouseReleaseEvent(self, event):
            self.record('mouse_up', int(event.button()))

    window = Receiver()
    window.setWindowTitle('mcpy input timing test (isolated receiver)')
    window.resize(400, 240)
    window.move(60, 60)
    window.show()
    state = {'hwnd': int(window.winId()), 'pid': os.getpid()}
    args.state.write_text(json.dumps(state), encoding='utf-8')
    output = args.state.with_suffix('.events.json')
    stop = args.state.with_suffix('.stop')

    def flush():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(events), encoding='utf-8')
        temporary.replace(output)
        if stop.exists():
            app.quit()

    timer = QTimer()
    timer.timeout.connect(flush)
    timer.start(20)
    QTimer.singleShot(30000, app.quit)
    app.exec()
    flush()


if __name__ == '__main__':
    main()
