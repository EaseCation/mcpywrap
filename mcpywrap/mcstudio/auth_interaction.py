"""Human-only recovery for the optional identity feature; no silent certificate trust."""
import json
import os
from pathlib import Path
import subprocess


def _powershell_json(script, directory):
    environment = dict(os.environ, MCPY_BRIDGE_CHECK=str(directory))
    environment = {k: v for k, v in environment.items() if k.casefold() != 'psmodulepath'}
    powershell = str(Path(os.environ.get('WINDIR', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')
    result = subprocess.run([powershell, '-NoProfile', '-Command', script],
                            env=environment, capture_output=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        return None


def certificate_can_help(directory, certificate):
    """Offer recovery only for intact signatures terminating at an untrusted root."""
    script = r'''
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$items=@()
foreach($name in @('Injector.exe','Loader.dll','McpyMcsAuth.dll')) {
 $sig=Get-AuthenticodeSignature -LiteralPath (Join-Path $env:MCPY_BRIDGE_CHECK $name)
 $untrusted=$false
 if($sig.SignerCertificate) {
  $chain=New-Object Security.Cryptography.X509Certificates.X509Chain
  $chain.ChainPolicy.RevocationMode='NoCheck'
  $valid=$chain.Build($sig.SignerCertificate)
  $states=@($chain.ChainStatus | ForEach-Object {$_.Status.ToString()})
  $untrusted=(!$valid -and $states.Count -eq 1 -and $states[0] -eq 'UntrustedRoot')
 }
 $items+=@{status=$sig.Status.ToString();thumbprint=$sig.SignerCertificate.Thumbprint;untrusted_root=$untrusted}
}
ConvertTo-Json -InputObject $items -Compress
'''
    try:
        result = _powershell_json(script, directory)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return isinstance(result, list) and len(result) == 3 and all(
        item.get('thumbprint') == certificate['thumbprint'] and item.get('untrusted_root') and
        item.get('status') in ('UnknownError', 'NotTrusted') for item in result)


def confirm_certificate(certificate):
    from PyQt5.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    dialog = QMessageBox()
    dialog.setWindowTitle('启用 MC Studio 登录身份')
    dialog.setIcon(QMessageBox.Warning)
    dialog.setText('Windows 尚未信任 mcpywrap 登录组件的发布者。')
    dialog.setInformativeText(
        '此组件会读取你在 MC Studio 中已登录的身份，用于启动本次游戏。\n\n'
        '你可以将发布者证书加入当前 Windows 用户的信任列表，再试一次。'
        '这也会信任同一证书签署的其他程序，并非只允许本次运行。\n\n'
        '部分电脑仍会受智能应用控制或组织策略限制，安装证书不保证能够启用。'
        '取消后仍可去掉 --mcs-auth 进行普通测试。')
    dialog.setDetailedText('发布者：'+certificate['subject']+'\n证书指纹：'+certificate['thumbprint']+
                           '\n有效期至：'+certificate['expires']+
                           '\n仅安装公钥证书，不安装私钥，不关闭 Windows 安全保护。')
    accept = dialog.addButton('信任此发布者并重试', QMessageBox.AcceptRole)
    cancel = dialog.addButton('暂不启用', QMessageBox.RejectRole)
    dialog.setDefaultButton(cancel)
    dialog.exec_()
    return dialog.clickedButton() is accept


def install_certificate(certificate):
    # Called only after the explicit consent above. No system-wide store or elevation.
    command = str(Path(os.environ.get('WINDIR', r'C:\Windows'))/'System32/certutil.exe')
    result = subprocess.run([command, '-user', '-addstore', 'Root', certificate['path']],
                            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError('证书未能安装。可能缺少权限或被组织策略限制；你仍可不带 --mcs-auth 进行普通测试。')


def show_failure(message):
    from PyQt5.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    QMessageBox.warning(None, '暂时无法使用 MC Studio 登录身份', message)
