"""从固定的 Tracy 0.11.1 源码构建 mcpy 分析工具包（分析器界面、采集、CSV 导出、JSON 报告）。

用法：
    python native/tracy_tools/build.py --work <构建目录> --output <输出目录> [--source <Tracy 检出>] [--build 1]

源码不存在时按固定标签克隆并核对提交；构建依赖由 Tracy 自身的 CPM 下载。
输出 mcpy-tracy-<版本>-<构建号>-<平台>.zip 及同名 .json（文件名、大小、sha256），
用于发布后写入 core/mcpywrap_core/profiling/tools.json。不安装、不启动任何程序。
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

TRACY_VERSION = '0.11.1'
TRACY_TAG = 'v0.11.1'
TRACY_COMMIT = '5d542dc09f3d9378d005092a4ad446bd405f819a'
TRACY_PROTOCOL = 69
TRACY_REPOSITORY = 'https://github.com/wolfpld/tracy.git'
HERE = Path(__file__).resolve().parent
# 构建目标：Tracy 源码子目录 → 可执行文件名
TARGETS = {
    'profiler': ('profiler', 'tracy-profiler'),
    'capture': ('capture', 'tracy-capture'),
    'csvexport': ('csvexport', 'tracy-csvexport'),
    'report': ('mcpy-report', 'mcpy-tracy-report'),
}


def platform_tag():
    machine = platform.machine().lower()
    if sys.platform == 'darwin' and machine == 'arm64':
        return 'macos-arm64'
    if os.name == 'nt' and machine in ('amd64', 'x86_64'):
        return 'windows-x64'
    raise SystemExit('不支持的构建平台：%s %s' % (sys.platform, machine))


def run(command, **kwargs):
    print('+ ' + ' '.join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def prepare_source(source):
    if not source.exists():
        run(['git', 'clone', '--depth', '1', '--branch', TRACY_TAG, TRACY_REPOSITORY, source])
    head = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != TRACY_COMMIT:
        raise SystemExit('Tracy 源码提交为 %s，应为 %s（%s）' % (head, TRACY_COMMIT, TRACY_TAG))
    apply_source_fixes(source)
    # 报告工具复用 Tracy 的 cmake 配置，需要位于源码根目录下
    target = source/'mcpy-report'
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(HERE/'report', target)


# 只修复与新编译器的兼容问题，不改变行为；记录在 BUILDINFO.json 中
SOURCE_FIXES = [
    # 新版 MSVC STL 不再间接包含 <chrono>；上游后续版本同样补上了此包含
    ('profiler/src/profiler/TracyView.hpp', '#include <atomic>\n', '#include <atomic>\n#include <chrono>\n'),
]


def apply_source_fixes(source):
    for relative, old, new in SOURCE_FIXES:
        path = source/relative
        text = path.read_text(encoding='utf-8')
        if new in text:
            continue
        if text.count(old) != 1:
            raise SystemExit('源码修正位置不唯一：' + relative)
        path.write_text(text.replace(old, new), encoding='utf-8')


def build_target(source, work, name):
    directory, executable = TARGETS[name]
    build = work/name
    configure = ['cmake', '-S', source/directory, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
                 '-DNO_ISA_EXTENSIONS=ON', '-DCPM_SOURCE_CACHE=' + str(work/'cpm-cache'),
                 # 固定版本源码静态链接，不使用构建机上的 Homebrew/pkg-config 动态库
                 '-DDOWNLOAD_CAPSTONE=ON', '-DDOWNLOAD_GLFW=ON', '-DDOWNLOAD_FREETYPE=ON',
                 '-DFT_DISABLE_PNG=ON', '-DFT_DISABLE_BZIP2=ON', '-DFT_DISABLE_BROTLI=ON',
                 '-DFT_DISABLE_HARFBUZZ=ON', '-DBUILD_SHARED_LIBS=OFF',
                 # CMake 4 拒绝 freetype 2.13.2 等依赖声明的过旧最低版本；CMake 3 忽略此项
                 '-DCMAKE_POLICY_VERSION_MINIMUM=3.5']
    if os.name == 'nt':
        # 静态链接 MSVC 运行库，不依赖目标机的 VC++ 可再发行组件版本（如 MSVCP140_ATOMIC_WAIT.dll）；
        # 依赖子项目的最低版本较旧，需同时把 CMP0091 默认设为 NEW，保证全部目标一致
        configure += ['-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded', '-DCMAKE_POLICY_DEFAULT_CMP0091=NEW']
    # Windows 只在已进入 MSVC 环境时用 Ninja，否则使用 Visual Studio 生成器
    if shutil.which('ninja') and (os.name != 'nt' or os.environ.get('VCINSTALLDIR')):
        configure[1:1] = ['-G', 'Ninja']
    env = dict(os.environ)
    if sys.platform == 'darwin':
        env.setdefault('MACOSX_DEPLOYMENT_TARGET', '13.0')
    run(configure, env=env)
    run(['cmake', '--build', build, '--config', 'Release', '--parallel'], env=env)
    suffix = '.exe' if os.name == 'nt' else ''
    for candidate in (build/(executable+suffix), build/'Release'/(executable+suffix)):
        if candidate.is_file():
            return candidate
    raise SystemExit('未找到构建产物：' + executable)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def package(source, binaries, output, build_number, tag):
    output.mkdir(parents=True, exist_ok=True)
    name = 'mcpy-tracy-%s-%s-%s' % (TRACY_VERSION, build_number, tag)
    archive = output/(name+'.zip')
    info = {'schema': 1, 'tracy_version': TRACY_VERSION, 'tracy_commit': TRACY_COMMIT,
            'protocol': TRACY_PROTOCOL, 'build': build_number, 'platform': tag,
            'source_fixes': [relative for relative, _, _ in SOURCE_FIXES],
            'files': {path.name: sha256(path) for path in binaries}}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in binaries:
            member = zipfile.ZipInfo('mcpy-tracy/'+path.name, date_time=(2024, 8, 22, 0, 0, 0))
            member.external_attr = 0o100755 << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(member, path.read_bytes())
        bundle.write(source/'LICENSE', 'mcpy-tracy/LICENSE')
        bundle.writestr('mcpy-tracy/BUILDINFO.json', json.dumps(info, indent=2, sort_keys=True))
    entry = {'platform': tag, 'filename': archive.name, 'size': archive.stat().st_size, 'sha256': sha256(archive)}
    (output/(name+'.json')).write_text(json.dumps(entry, indent=2) + '\n')
    print(json.dumps(entry, indent=2))
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, help='Tracy 源码检出目录，默认 <work>/tracy-src')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build', default='1', help='同一 Tracy 版本的打包序号')
    parser.add_argument('--targets', default=','.join(TARGETS))
    args = parser.parse_args()
    work = args.work.resolve()
    source = (args.source or work/'tracy-src').resolve()
    tag = platform_tag()
    prepare_source(source)
    binaries = []
    for name in args.targets.split(','):
        binary = build_target(source, work, name)
        if sys.platform == 'darwin':
            run(['codesign', '--force', '--sign', '-', binary])
        binaries.append(binary)
    package(source, binaries, args.output.resolve(), args.build, tag)


if __name__ == '__main__':
    main()
