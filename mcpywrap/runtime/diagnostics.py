"""Lossless, credential-redacted diagnostics across process and UI boundaries."""


def diagnostic(error, secrets=()):
    from ..mcstudio.private_logs import Redactor

    value = {
        "error": str(error),
        "code": getattr(error, "code", "launch_failed"),
        "hint": getattr(error, "hint", None),
        "details": getattr(error, "details", {}),
    }

    # Redact serialized strings as well as messages, without flattening arbitrary details.
    def redact(item):
        if isinstance(item, str):
            return Redactor(secrets).feed(item, final=True)
        if isinstance(item, dict):
            return {k: redact(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [redact(v) for v in item]
        return item

    value = redact(value)
    value["actions"] = value["details"].get("actions", [])
    value["operation_id"] = value["details"].get("operation_id")
    return value


def exception(value, message=None, **context):
    from ..engines.host import EngineError

    details = dict(value.get("details") or value.get("script_error") or {})
    details.update(context)
    for key in ("actions", "operation_id"):
        if value.get(key) is not None:
            details[key] = value[key]
    return EngineError(
        message or value.get("error") or "操作失败",
        value.get("code", "launch_failed"),
        value.get("hint"),
        **details,
    )


def powershell_command(argv):
    return "& " + " ".join("'" + str(arg).replace("'", "''") + "'" for arg in argv)


def format_diagnostic(value):
    lines = [value.get("error") or value.get("code") or "操作失败"]
    if value.get("hint"):
        lines.append(value["hint"])
    for conflict in (value.get("details") or {}).get("conflicts", []):
        lines.append(
            "{} {}\n  当前：{}\n  冲突：{}\n  归属：{}".format(
                conflict["kind"],
                conflict["uuid"],
                conflict.get("source", ""),
                conflict["path"],
                conflict.get("project") or "未知",
            )
        )
    script_log = (value.get("details") or {}).get("script_log") or value.get(
        "script_log"
    )
    if script_log:
        lines.append("脚本日志: " + script_log)
    actions = value.get("actions") or (value.get("details") or {}).get("actions") or []
    for action in actions:
        if action.get("argv"):
            command = powershell_command(action["argv"])
            lines.append(action.get("label", "下一步") + "（只读预览）：\n" + command)
    return "\n".join(lines)
