"""无 Qt、无输入线程的文件日志接收器。"""
import socket
import threading
from .log_protocol import LogDecoder


class FileLogServer:
    def __init__(self, path, decoder_factory=LogDecoder):
        self.decoder_factory = decoder_factory
        self.stream = open(path, 'a', encoding='utf-8')
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.port = self.socket.getsockname()[1]
        self.socket.listen(5)
        self.socket.settimeout(0.2)
        self.clients = []
        self.thread = threading.Thread(target=self._accept, daemon=True)

    def start(self):
        self.thread.start()

    def _accept(self):
        while not self.stop_event.is_set():
            try:
                client, _ = self.socket.accept()
                client.settimeout(0.2)
                thread = threading.Thread(target=self._read, args=(client,), daemon=True)
                self.clients.append((client, thread))
                thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _write(self, text):
        with self.lock:
            self.stream.write(text)
            self.stream.flush()

    def _read(self, client):
        decoder = self.decoder_factory()
        try:
            while not self.stop_event.is_set():
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                self._write(decoder.feed(data))
            self._write(decoder.finish())
        except OSError:
            pass
        finally:
            client.close()

    def close(self):
        self.stop_event.set()
        self.socket.close()
        self.thread.join(timeout=1)
        for client, thread in self.clients:
            thread.join(timeout=1)
            client.close()
        self.stream.close()
