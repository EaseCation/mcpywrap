from __future__ import print_function

import logging
import sys
from lib2to3 import refactor
from lib2to3.main import StdoutRefactoringTool


def py3_to_2(directory):
    """将指定目录的Python文件从Python 3转换为Python 2"""
    fixer_pkg = 'lib3to2.fixes'
    processes = 4

    # 设置日志处理器
    level = logging.INFO
    logging.basicConfig(format='%(name)s: %(message)s', level=level)

    # 初始化重构工具
    avail_fixes = set(refactor.get_fixers_from_package(fixer_pkg))
    nofix = ['metaclass']
    unwanted_fixes = set(fixer_pkg + ".fix_" + fix for fix in nofix)
    explicit = set()
    requested = avail_fixes.union(explicit)
    fixer_names = requested.difference(unwanted_fixes)

    # 正确初始化StdoutRefactoringTool
    rt = StdoutRefactoringTool(
        sorted(fixer_names),       # fixers
        {},                        # options字典
        sorted(explicit),          # explicit
        nobackups=True,            # 不创建备份
        show_diffs=False,          # 不显示差异
        input_base_dir='',         # 输入基础目录
        output_dir='',             # 不使用单独输出目录(原位替换)
        append_suffix=''           # 不添加后缀
    )

    print("使用以下修复器进行重构:")
    for fix in sorted(fixer_names):
        print("  ", fix)

    # 重构所有文件
    if not rt.errors:
        try:
            # 关键点：传递正确的文件路径列表，以及write=True启用写入
            rt.refactor([directory], write=True, doctests_only=False, num_processes=processes)
        except refactor.MultiprocessingUnsupported:
            print("抱歉，此平台不支持多进程转换。", file=sys.stderr)
            return 1
        rt.summarize()

    # 返回错误状态(如果rt.errors为0则返回0)
    return int(bool(rt.errors))