"""Qt adapters for common session operations; no platform selection here."""
import codecs
from pathlib import Path
from PySide6.QtCore import QThread, Signal


class TaskThread(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as error:
            hint = getattr(error, 'hint', None)
            self.failed.emit(str(error) + ('\n' + hint if hint else ''))
        finally:
            self.function = None


class LogTail:
    def __init__(self):
        self.reset()

    def reset(self):
        self.path, self.offset, self.pending = None, 0, ''
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')

    def read(self, path):
        path = Path(path)
        if self.path != path:
            self.reset(); self.path = path
        if not path.is_file(): return ''
        if path.stat().st_size < self.offset:
            self.reset(); self.path = path
        with path.open('rb') as stream:
            stream.seek(self.offset)
            block = stream.read(65536)
            self.offset = stream.tell()
        text = self.pending + self.decoder.decode(block)
        position = text.rfind('\n')
        if position < 0:
            self.pending = text[-1048576:]
            return ''
        self.pending = text[position+1:]
        return text[:position+1]


class DebugLogFilter:
    """Hide protocol/script echoes in the view; raw session files remain complete."""
    def __init__(self):
        self.in_script = False

    def apply(self, text):
        visible = []
        for line in text.splitlines(keepends=True):
            if '[Run]' in line and 'script begin' in line:
                self.in_script = True; continue
            if '[Run]' in line and 'script end' in line:
                self.in_script = False; continue
            if self.in_script or any(marker in line for marker in ('RN Call:', 'RN Return:', '__MCPY_RESULT_')):
                continue
            visible.append(line)
        return ''.join(visible)
