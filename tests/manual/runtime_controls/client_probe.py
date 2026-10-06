# coding: utf-8
"""OPTIONAL GAME-CLIENT PROBE. Run after the public runtime install command."""
_result = {
    'ui': mcpy.ui.capabilities(),
    'player': mcpy.player.capabilities(),
    'top': mcpy.api.GetTopUI(),
    'world': mcpy.api.GetLevelId(),
}
