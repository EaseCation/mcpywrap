"""本地联机的有限菜单状态识别。只从本次客户区观测选择操作。"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Action:
    kind: str
    text: str
    point: tuple


def compact(text):
    return re.sub(r'\s+', '', text).casefold()


def host_match(text, player):
    # 仅消除像素字体中已观察到的字形混淆，不使用编辑距离补齐或截断身份。
    text = re.sub(r'[^a-z0-9]', '', text.casefold().replace('ø', '0'))
    player = re.sub(r'[^a-z0-9]', '', player.casefold())
    equivalents = {'0': '0o', '1': '1il', '8': '8s', '5': '5s'}
    return (bool(player) and text[len(player):] in ('','world','sworld') and len(text) >= len(player) and
            all(actual in equivalents.get(expected,expected) for actual,expected in zip(text,player)))


def choose(view, player, selected=False, bootstrap=False):
    width, height = view.get('width'), view.get('height')
    if type(width) is not int or type(height) is not int or not 1 <= width*height <= 16*1024**2:
        raise ValueError('无效的菜单观测尺寸')
    rows = []
    for line in view.get('lines', ()):
        text, bounds = line.get('text'), line.get('bounds')
        if not isinstance(text, str) or not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError('无效的菜单文字观测')
        left, top, right, bottom = bounds
        if not all(isinstance(n, (int,float)) for n in bounds) or not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError('菜单观测坐标越界')
        # 排除版本/debug HUD；页脚也不是加入目标。
        if top < height*.065 or bottom > height*.94:
            continue
        rows.append((text, compact(text), ((left+right)/2, (top+bottom)/2)))

    def unique(kind, predicate):
        matches = [Action(kind, text, point) for text, normal, point in rows if predicate(normal, text)]
        dedup = []
        for action in matches:
            if not any(abs(action.point[0]-other.point[0])<width*.03 and
                       abs(action.point[1]-other.point[1])<height*.025 for other in dedup):
                dedup.append(action)
        if len(dedup)>1:
            raise ValueError('菜单中有多个相同操作目标，拒绝猜测：'+kind)
        return dedup[0] if dedup else None

    if bootstrap:
        return unique('leave_bootstrap',lambda n,t: n in ('保存并退出','儲存並離開','保存并退岀','save&quit','saveandquit'))
    if selected:
        download = unique('download',lambda n,t: n.startswith(('全部下载并加入','downloadall&join','downloadallandjoin','全部下載並加入')))
        if not download:
            download = unique('download',lambda n,t: n.startswith(('下载必要资源包并加入','download&join','downloadandjoin','下載並加入')))
        if download:
            return download
        # 只有已经选中了当前主机卡片，才允许确认首次联机提示。
        if any(any(mark in n for mark in ('线上游戏未分级','onlineplayisnotrated','線上遊戲未分級')) for t,n,p in rows):
            return unique('confirm',lambda n,t: n in ('继续','繼續','continue'))
        return None
    target = unique('host',lambda n,t: host_match(t,player))
    if target:
        return target
    more = unique('more',lambda n,t: n in ('更多选项','更多選項','moreoptions'))
    if more:
        return more
    return unique('play',lambda n,t: n in ('开始游戏','開始遊戲','play','playgame','开始渫戏'))
