"""Explicit handoff to a human for application visibility/permission recovery."""

USER_ACTION_CODES = frozenset({
    'host_unavailable', 'host_service_required', 'vendor_background_launch_denied',
    'background_launch_unconfirmed', 'launch_blocked_by_os', 'game_presentation_pending',
    'game_start_unknown', 'pip_not_confirmed', 'pip_permission_missing',
    'overlay_permission_required', 'device_locked',
})


def require_user(error, operation_id=None):
    details=dict(getattr(error,'details',None) or {})
    if details.get('operation_state')!='waiting_user' and getattr(error,'code',None) not in USER_ACTION_CODES:
        return False
    offline=getattr(error,'code',None)=='host_unavailable'
    message=('请在手机上手动打开 mcpy，在“开发”页确认开发连接已开启，连接恢复后可返回当前工具，再告诉我。若切换应用后又断连，请在该页打开省电设置，小米选择“无限制”。'
             if offline else
             '请在手机上手动切回 mcpy，继续这次启动或恢复游戏画面；完成后告诉我。')
    if not offline:
        message+='如果希望以后直接从开发工具启动，请在系统应用权限中允许 mcpy 的“后台弹出界面”，并检查画中画权限；各品牌入口可能不同。'
    if getattr(error,'code',None)=='device_locked': message='请先解锁手机。'+message
    instruction=('立即停止自动尝试，把 user_message 告诉用户并等待用户明确确认。'
                 '不要自动 run、restart、重新构建、新建世界、循环轮询或执行 android-open、am start、恢复 URI 或其他唤起/权限绕过方式。'
                 '收到用户确认后，只查询或恢复原任务；不要把用户未回复当作已处理。')
    details.update(needs_user_action=True,next_action='ask_user',retryable=False,
                   retry_policy='after_user_confirmation',user_message=message,agent_instruction=instruction)
    operation_id=operation_id or details.get('operation_id')
    if operation_id:
        details['operation_id']=operation_id
        details['resume_command']='mcpy host resume --operation '+operation_id+' --json'
    # Do not fabricate prepared/session/running state when the host was unreachable.
    details['recovery_uri']='mcpy://service/start'
    previous=getattr(error,'hint',None) or ''
    notice='需要用户操作，请停止自动重试。'+message
    if '需要用户操作，请停止自动重试。' not in previous:
        error.hint=notice+(' 原因与诊断：'+previous if previous else '')
    if operation_id and details['resume_command'] not in error.hint:
        error.hint+=' 等用户确认后执行 '+details['resume_command']+' 查询原任务；不要重新 run --new。'
    details['hint']=error.hint
    error.details=details
    return True
