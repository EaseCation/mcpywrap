"""Streaming credential redaction, including secrets split across read boundaries."""
import threading

from .log_protocol import LogDecoder, TextLogDecoder


class Redactor:
    def __init__(self, secrets=()):
        values = set(str(s) for s in secrets if s)
        # Include escaped spellings when a game emits JSON rather than plain text.
        import json
        values.update(json.dumps(s, ensure_ascii=True)[1:-1] for s in list(values))
        self.secrets = sorted(values, key=len, reverse=True)
        self.keep = max(map(len, self.secrets), default=1)-1
        self.pending = ''

    def feed(self, text, final=False):
        self.pending += text
        limit = len(self.pending) if final else max(0, len(self.pending)-self.keep)
        result, at = [], 0
        while at < limit:
            found = next((s for s in self.secrets if self.pending.startswith(s, at)), None)
            if found:
                result.append('<redacted>'); at += len(found)
            else:
                result.append(self.pending[at]); at += 1
        self.pending = self.pending[at:]
        return ''.join(result)


class RedactedDecoder:
    """Per-connection SDK decoder; redact before FileLogServer persists text."""
    def __init__(self, secrets):
        self.decoder, self.redactor = LogDecoder(), Redactor(secrets)

    def feed(self, data):
        return self.redactor.feed(self.decoder.feed(data))

    def finish(self):
        return self.redactor.feed(self.decoder.finish(), final=True)


class EngineLogCapture:
    def __init__(self, stream, path, secrets=()):
        self.stream, self.path, self.secrets = stream, path, secrets
        self.error = None
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        decoder = TextLogDecoder()
        redactor = Redactor(self.secrets)
        try:
            with open(self.path, 'w', encoding='utf-8', newline='') as output:
                while True:
                    chunk = getattr(self.stream, 'read1', self.stream.read)(4096)
                    if not chunk:
                        output.write(redactor.feed(decoder.finish(), final=True))
                        break
                    output.write(redactor.feed(decoder.feed(chunk)))
                    output.flush()
        except (OSError, ValueError) as exc:
            self.error = type(exc).__name__
        finally:
            self.stream.close()

    def close(self):
        self.thread.join(timeout=5)
        if self.thread.is_alive() or self.error:
            raise OSError('引擎日志收集未正常结束')
