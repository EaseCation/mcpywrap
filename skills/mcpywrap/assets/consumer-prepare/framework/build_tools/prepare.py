"""示例：把消费者的原始 JSON 转成游戏包内的目录数据，仅使用标准库。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.catalog-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    root = Path(os.environ['MCPY_PROJECT_ROOT']).resolve()
    config = json.loads(Path(os.environ['MCPY_CONSUMER_CONFIG']).read_text(encoding='utf-8'))
    source = (root / config['source']).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError('tool.catalog.source：请选择消费项目内已存在的原始 JSON 文件。')
    values = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(values, dict) or any(not key or type(value) is not int or value < 0 for key, value in values.items()):
        raise ValueError(str(source) + '：需要非空名称到非负整数的映射，例如 {"apple": 5}。')
    destination = root / 'behavior_pack/generated/catalog.json'
    ledger = root / '.mcpy/catalog-example/owned.json'
    for path in (destination, ledger):
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents) if p != root):
            raise ValueError('生成位置不能经过目录链接：' + str(path))
    previous = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
    current = destination.read_bytes() if destination.exists() else None
    if current is not None and hashlib.sha256(current).hexdigest() != previous.get('sha256'):
        raise ValueError('生成文件未归本工具所有或已被手动编辑；请先保存并检查：' + str(destination))
    content = (json.dumps(values, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if content != current:
        atomic_write(destination, content)
    state = (json.dumps({'sha256': hashlib.sha256(content).hexdigest()}) + '\n').encode('utf-8')
    if not ledger.exists() or ledger.read_bytes() != state:
        atomic_write(ledger, state)
    print('资源目录准备完成：%d 项，更新 %d 个资源文件。' % (len(values), int(content != current)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print('无法准备目录资源：' + str(exc), file=sys.stderr)
        sys.exit(1)
