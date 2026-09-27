param(
    [string]$Version,
    [string]$GitRef,
    [string]$EditablePath,
    [string]$Python = '3.12',
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'

function Fail([string]$Message) {
    @{ ok = $false; error = $Message } | ConvertTo-Json -Compress
    exit 1
}

function Capabilities([string]$Command) {
    $helpText = (& $Command --help 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { return $false }
    foreach ($entry in @('--project', '--non-interactive', '--json', 'status', 'logs', 'stop', 'package')) {
        if (!$helpText.Contains($entry)) { return $false }
    }
    $runHelp = (& $Command run --help 2>&1 | Out-String)
    return $LASTEXITCODE -eq 0 -and $runHelp.Contains('--detach') -and $runHelp.Contains('--no-gui')
}

try {
    if (@($Version, $GitRef, $EditablePath | Where-Object { $_ }).Count -gt 1) {
        Fail 'Version、GitRef、EditablePath 只能选择一种来源'
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (!$uv) { Fail '需要 uv；安装入口：https://docs.astral.sh/uv/getting-started/installation/' }
    $bin = (& $uv.Source tool dir --bin | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { Fail '无法查询 uv 工具目录' }
    $commandPath = Join-Path $bin 'mcpy.exe'
    $existing = Test-Path -LiteralPath $commandPath
    if ($existing -and !$Upgrade) {
        if (!(Capabilities $commandPath)) { Fail '现有 mcpy 缺少所需能力；显式指定版本或源码，并使用 -Upgrade' }
        $installedVersion = (& $commandPath --version | Out-String).Trim()
        if ($GitRef -or $EditablePath -or ($Version -and !$installedVersion.EndsWith($Version))) {
            Fail '已有安装；更换指定来源或版本需要 -Upgrade'
        }
    } else {
        $installArgs = @('tool', 'install', '--python', $Python)
        if ($Upgrade) { $installArgs += @('--force', '--upgrade') }
        if ($GitRef) {
            if ($GitRef -notmatch '^[0-9a-fA-F]{40}$') { Fail 'GitRef 必须是完整的 40 位提交 SHA' }
            $installArgs += "git+https://github.com/EaseCation/mcpywrap.git@$GitRef"
        } elseif ($EditablePath) {
            $resolved = (Resolve-Path -LiteralPath $EditablePath).Path
            if (!(Test-Path -LiteralPath (Join-Path $resolved 'pyproject.toml'))) { Fail 'EditablePath 缺少 pyproject.toml' }
            $installArgs += @('--editable', $resolved)
        } else {
            $installArgs += $(if ($Version) { "mcpywrap==$Version" } else { 'mcpywrap' })
        }
        $installOutput = & $uv.Source @installArgs 2>&1
        $installExit = $LASTEXITCODE
        foreach ($line in $installOutput) { [Console]::Error.WriteLine([string]$line) }
        if ($installExit -ne 0) { Fail 'uv 安装失败，请检查 stderr' }
        if (!(Capabilities $commandPath)) { Fail '安装的版本缺少 Skill 所需能力，请选择支持自动化 CLI 的版本或源码提交' }
        $installedVersion = (& $commandPath --version | Out-String).Trim()
    }
    @{ ok = $true; command = $commandPath; version = $installedVersion; capabilities = @('project', 'json', 'sessions', 'package') } | ConvertTo-Json -Compress
} catch {
    Fail $_.Exception.Message
}
