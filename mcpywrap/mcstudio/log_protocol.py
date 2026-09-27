"""Studio TCP 日志解码；兼容 UTF-8 与中国版引擎的 GB18030 文本。"""
import json


def decode_text(raw):
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('gb18030', errors='replace')


class LogDecoder:
    def __init__(self):
        self.pending = bytearray()
        self.frame = None

    def feed(self, data):
        output = []
        for index, piece in enumerate(data.split(b'\xff')):
            if index:
                if self.frame is None:
                    output.append(decode_text(bytes(self.pending)))
                    self.pending.clear()
                    self.frame = bytearray()
                else:
                    raw = decode_text(bytes(self.frame))
                    try:
                        raw = json.dumps(json.loads(raw), ensure_ascii=False)
                    except ValueError:
                        pass
                    output.append('[命令消息] ' + raw + '\n')
                    self.frame = None
            if self.frame is not None:
                self.frame.extend(piece)
                if len(self.frame) > 1024 * 1024:
                    output.append('[日志协议错误] 消息超过 1 MiB\n')
                    self.frame = None
            else:
                self.pending.extend(piece)
                while b'\n' in self.pending:
                    line, _, rest = self.pending.partition(b'\n')
                    output.append(decode_text(bytes(line)) + '\n')
                    self.pending = bytearray(rest)
                if len(self.pending) > 1024 * 1024:
                    output.append(decode_text(bytes(self.pending)))
                    self.pending.clear()
        return ''.join(output)

    def finish(self):
        value = decode_text(bytes(self.pending))
        self.pending.clear()
        return value
