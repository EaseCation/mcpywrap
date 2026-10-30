"""Human-readable packaging policy; structured data stays in operation results."""
from .utils.console import echo


def report_unbundled(result):
    if result.get('unbundled'):
        if result.get('included_in_release') is True:
            echo('打包设置：unbundled=true；本引用不随发布，共享节点仍通过其他打包引用进入产物。使用 deps --bundled-only 查看引用链。')
        else:
            echo('打包设置：unbundled=true；dev/run 加载，build/package 不包含。')
    else:
        echo('打包设置：unbundled=false（默认）；dev/run 加载，并进入 build/package。')
    previous = result.get('previous_unbundled')
    if previous is not None and previous != result.get('unbundled'):
        echo('打包设置已更新：%s → %s；运行中的会话需重启以应用。' %
             (str(previous).lower(), str(result['unbundled']).lower()))


def report_selection(selection):
    if not selection:
        return
    unbundled = sum(item['unbundled'] for item in selection['dependencies'])
    if selection['purpose'] == 'release':
        excluded = sum(item['reason'] == 'unbundled' for item in selection['excluded'])
        echo('依赖选择：构建发布；unbundled 依赖不进入产物%s。' % ('，已排除 %d 项' % excluded if excluded else ''))
    else:
        echo('依赖选择：本地运行；包含 %d 个 unbundled 依赖节点，这些节点不随 build/package 发布。' % unbundled)
