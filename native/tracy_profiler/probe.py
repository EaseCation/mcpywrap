"""可选手动工具：探测本机运行中游戏的内置 Tracy 端点及其协议版本。

不接入默认测试。成功握手会被游戏视为一次短暂的 viewer 连接，随后断开；
不要在正式采集时对同一端口运行。
"""
import argparse
import json
import socket
import struct

SHIBBOLETH = b'TracyPrf'
STATUS = {0: 'pending', 1: 'welcome', 2: 'protocol_mismatch', 3: 'not_available', 4: 'dropped'}


def handshake(host, port, protocol, timeout):
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(SHIBBOLETH + struct.pack('<I', protocol))
        reply = sock.recv(1)
    return reply[0] if reply else None


def detect(host, port, timeout, protocols):
    # 不匹配的握手会被客户端拒绝后继续等待，因此可以逐个尝试
    for protocol in protocols:
        status = handshake(host, port, protocol, timeout)
        if status != 2:
            return {'host': host, 'port': port, 'protocol': protocol if status == 1 else None,
                    'status': STATUS.get(status, status)}
    return {'host': host, 'port': port, 'protocol': None, 'status': 'protocol_unknown'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='append', help='默认 127.0.0.1 与 ::1')
    parser.add_argument('--ports', default='8086-8105')
    parser.add_argument('--timeout', type=float, default=2.0)
    parser.add_argument('--max-protocol', type=int, default=200)
    args = parser.parse_args()
    first, _, last = args.ports.partition('-')
    ports = range(int(first), int(last or first) + 1)
    protocols = range(args.max_protocol, 0, -1)
    found = []
    for host in args.host or ['127.0.0.1', '::1']:
        for port in ports:
            try:
                found.append(detect(host, port, args.timeout, protocols))
            except OSError:
                continue
    print(json.dumps(found, ensure_ascii=False, indent=2))
    return 0 if found else 1


if __name__ == '__main__':
    raise SystemExit(main())
