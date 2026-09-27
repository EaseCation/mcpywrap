param(
    [string]$Version,
    [string]$GitRef,
    [string]$EditablePath,
    [string]$Python = '3.12',
    [ValidateSet('network', 'network-sessions', 'mcs-auth')]
    [string[]]$RequireCapability = @(),
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
# Native pipes have an explicit encoding, including in Windows PowerShell 5.1.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'

function Fail([string]$Message) {
    @{ ok = $false; error = $Message } | ConvertTo-Json -Compress
    exit 1
}

function Capabilities([string]$Command) {
    $helpText = (& $Command --help 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { return $null }
    foreach ($entry in @('--project', '--non-interactive', '--json', 'status', 'logs', 'stop', 'package')) {
        if (!$helpText.Contains($entry)) { return $null }
    }
    $runHelp = (& $Command run --help 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or !$runHelp.Contains('--detach') -or !$runHelp.Contains('--no-gui')) { return $null }
    $features = @('project', 'json', 'sessions', 'package')
    if ($helpText -match '(?m)^\s+connect\s') {
        $connectHelp = (& $Command connect --help 2>&1 | Out-String)
        if ($LASTEXITCODE -eq 0) {
            $features += 'network'
            if ($connectHelp.Contains('--detach')) { $features += 'network-sessions' }
        }
    }
    $auth = @{ supported = $runHelp.Contains('--mcs-auth'); component_available = $null;
               hint = '当前 CLI 无组件诊断能力；参数支持不代表组件已具备。' }
    if ($auth.supported) {
        $features += 'mcs-auth'
        $doctorHelp = (& $Command doctor --help 2>&1 | Out-String)
        if ($LASTEXITCODE -eq 0 -and $doctorHelp.Contains('--mcs-auth')) {
            # Engine readiness may fail independently. Read the component result, not the exit code.
            $raw = (& $Command --non-interactive doctor --mcs-auth --json 2>$null | Out-String)
            try {
                $diagnosis = $raw | ConvertFrom-Json
                if ($null -ne $diagnosis.mcs_auth) {
                    $auth.component_available = $diagnosis.mcs_auth.component_available
                    $auth.diagnostics = $diagnosis.mcs_auth
                    $auth.hint = $diagnosis.mcs_auth.hint
                }
            } catch { $auth.hint = '组件诊断未返回有效 JSON；请运行 doctor --mcs-auth --json 检查。' }
        }
    }
    return @{ capabilities = $features; mcs_auth = $auth }
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
        $detected = Capabilities $commandPath
        if (!$detected) { Fail '现有 mcpy 缺少所需能力；显式指定版本或源码，并使用 -Upgrade' }
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
        $detected = Capabilities $commandPath
        if (!$detected) { Fail '安装的版本缺少 Skill 所需能力，请选择支持自动化 CLI 的版本或源码提交' }
        $installedVersion = (& $commandPath --version | Out-String).Trim()
    }
    $missing = @($RequireCapability | Where-Object { $_ -notin $detected.capabilities })
    $errorText = $null
    if ($missing.Count) { $errorText = '缺少任务所需能力: ' + ($missing -join ', ') + '；使用 -Upgrade 显式更新。' }
    if ('mcs-auth' -in $RequireCapability -and $detected.mcs_auth.component_available -ne $true) {
        $errorText = 'MCS 身份组件未就绪或无法检查；请使用正式发布包，或准备源码构建的桥接组件。'
    }
    @{ ok = !$errorText; error = $errorText; command = $commandPath; version = $installedVersion;
       capabilities = $detected.capabilities; mcs_auth = $detected.mcs_auth } | ConvertTo-Json -Depth 6 -Compress
    if ($errorText) { exit 1 }
} catch {
    Fail $_.Exception.Message
}
