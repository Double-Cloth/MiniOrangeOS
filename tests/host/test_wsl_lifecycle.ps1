[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$WslDirectory = Join-Path $RepoRoot 'environment\wsl'
$CreateScript = Join-Path $WslDirectory 'create.ps1'
$EnterScript = Join-Path $WslDirectory 'enter.ps1'
$BackupScript = Join-Path $WslDirectory 'backup.ps1'
$DestroyScript = Join-Path $WslDirectory 'destroy.ps1'
. (Join-Path $WslDirectory 'common.ps1')
$PathConfiguration = Get-MiniosWslPathConfiguration -WslDirectory $WslDirectory
$ProductionAuthorizedRoot = $PathConfiguration.AuthorizedRoot
$RepoWslPath = ConvertTo-MiniosWslPath $PathConfiguration.RepoRoot
$Script:Passed = 0
$Script:Failed = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Test {
    param([string]$Name, [scriptblock]$Body)
    try {
        & $Body
        $Script:Passed++
        Write-Host "PASS $Name"
    }
    catch {
        $Script:Failed++
        Write-Host "FAIL $Name :: $($_.Exception.Message)"
    }
}

function Read-FakeLog {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return ''
    }
    return [IO.File]::ReadAllText($Path)
}

function Reset-FakeLog {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Invoke-WithFakeLxss {
    param(
        [string]$ScriptPath,
        [hashtable]$Arguments,
        [string]$RegisteredName,
        [string]$RegisteredBasePath,
        [int]$RegisteredVersion = 2
    )

    function Get-ChildItem {
        param([string]$LiteralPath)
        [pscustomobject]@{ PSPath = 'HKCU:\FakeLxss\{11111111-2222-3333-4444-555555555555}' }
    }
    function Get-ItemProperty {
        param([string]$LiteralPath)
        [pscustomobject]@{
            DistributionName = $RegisteredName
            BasePath = $RegisteredBasePath
            Version = $RegisteredVersion
        }
    }
    function wsl.exe {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
        [IO.File]::AppendAllText($env:FAKE_WSL_LOG, (($Arguments -join ' ') + "`n"))
        if ($env:FAKE_WSL_JSON_LOG) {
            [IO.File]::AppendAllText($env:FAKE_WSL_JSON_LOG, ((ConvertTo-Json -Compress -InputObject @($Arguments)) + "`n"))
        }
        if ($Arguments.Count -ge 2 -and $Arguments[0] -ceq '--list') {
            Write-Output $env:FAKE_WSL_LIST
        }
        if ($Arguments.Count -ge 2 -and $Arguments[0] -ceq '--terminate' -and $env:FAKE_WSL_TERMINATE_PARTIAL) {
            [IO.File]::WriteAllText($env:FAKE_WSL_TERMINATE_PARTIAL, 'concurrent-unknown', [Text.Encoding]::UTF8)
        }
        if ($Arguments.Count -ge 3 -and $Arguments[0] -ceq '--export') {
            $Partial = $Arguments[2]
            switch ($env:FAKE_WSL_EXPORT_MODE) {
                'success' {
                    [IO.File]::WriteAllText($Partial, 'fake-backup', [Text.Encoding]::UTF8)
                }
                'failure' {
                    [IO.File]::WriteAllText($Partial, 'incomplete', [Text.Encoding]::UTF8)
                    $global:LASTEXITCODE = 7
                    return
                }
                'empty' {
                    [IO.File]::WriteAllBytes($Partial, [byte[]]@())
                }
                'junction' {
                    [void][IO.Directory]::CreateDirectory($env:FAKE_WSL_JUNCTION_TARGET)
                    [void](New-Item -ItemType Junction -Path $Partial -Target $env:FAKE_WSL_JUNCTION_TARGET)
                }
                'move-fail' {
                    [IO.File]::WriteAllText($Partial, 'fake-backup', [Text.Encoding]::UTF8)
                    [void][IO.Directory]::CreateDirectory($Partial.Substring(0, $Partial.Length - '.partial'.Length))
                }
            }
        }
        $global:LASTEXITCODE = 0
    }
    function Get-FileHash {
        param([string]$LiteralPath, [string]$Algorithm)
        if ($env:FAKE_FILE_HASH) {
            return [pscustomobject]@{ Hash = $env:FAKE_FILE_HASH }
        }
        return Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
    }

    & $ScriptPath @Arguments
}

foreach ($Path in @($CreateScript, $EnterScript, $BackupScript, $DestroyScript)) {
    Invoke-Test "PowerShell 解析：$([IO.Path]::GetFileName($Path))" {
        $Content = [IO.File]::ReadAllText($Path)
        [void][scriptblock]::Create($Content)
    }
}

$TemporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("minios-wsl-test-" + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($TemporaryRoot)
$AuthorizedRoot = Join-Path $TemporaryRoot 'MiniOrangeOS'
$DistroName = 'MiniOrangeOS-Dev-Test-Lifecycle'
$InstallPath = Join-Path (Join-Path $AuthorizedRoot 'drills') $DistroName
$Downloads = Join-Path $AuthorizedRoot 'downloads'
$Exports = Join-Path $AuthorizedRoot 'exports'
[void][IO.Directory]::CreateDirectory($InstallPath)
[void][IO.Directory]::CreateDirectory($Downloads)
[void][IO.Directory]::CreateDirectory($Exports)
$FakeWsl = Join-Path $TemporaryRoot 'fake-wsl.cmd'
$FakeDownload = Join-Path $TemporaryRoot 'fake-download.cmd'
$FakeWslArguments = Join-Path $TemporaryRoot 'fake-wsl-arguments.exe'
$FakeLog = Join-Path $TemporaryRoot 'wsl.log'
$DownloadLog = Join-Path $TemporaryRoot 'download.log'
[IO.File]::WriteAllText(
    $FakeWsl,
    "@echo off`r`necho %* >> `"%FAKE_WSL_LOG%`"`r`nif `"%1`"==`"--list`" echo %FAKE_WSL_LIST%`r`nexit /b 0`r`n",
    [Text.Encoding]::ASCII
)
$FakeArgumentSource = @'
using System;
using System.IO;
using System.Text;

public static class FakeWslArguments
{
    public static int Main(string[] args)
    {
        string log = Environment.GetEnvironmentVariable("FAKE_WSL_JSON_LOG");
        using (StreamWriter writer = File.AppendText(log))
        {
            writer.WriteLine("CALL");
            foreach (string argument in args)
            {
                writer.WriteLine("ARG=" + Convert.ToBase64String(Encoding.UTF8.GetBytes(argument)));
            }
        }
        if (args.Length > 0 && args[0] == "--list")
        {
            Console.WriteLine(Environment.GetEnvironmentVariable("FAKE_WSL_LIST"));
        }
        return 0;
    }
}
'@
Add-Type -TypeDefinition $FakeArgumentSource -Language CSharp -OutputAssembly $FakeWslArguments -OutputType ConsoleApplication -ErrorAction Stop
[IO.File]::WriteAllText(
    $FakeDownload,
    "@echo off`r`necho %*>>`"%FAKE_DOWNLOAD_LOG%`"`r`n>`"%2`" echo corrupt-rootfs`r`nexit /b 0`r`n",
    [Text.Encoding]::ASCII
)
$env:MINIOS_WSL_TEST_MODE = '1'
$env:FAKE_WSL_LOG = $FakeLog
$env:FAKE_WSL_LIST = $DistroName
$env:FAKE_DOWNLOAD_LOG = $DownloadLog

try {
    $DestroyBase = @{
        DistroName = $DistroName
        AuthorizedRoot = $AuthorizedRoot
        WslExecutable = 'wsl.exe'
    }

    Invoke-Test 'destroy 默认 preview 不注销' {
        Reset-FakeLog $FakeLog
        Invoke-WithFakeLxss $DestroyScript $DestroyBase $DistroName $InstallPath
        $Log = Read-FakeLog $FakeLog
        Assert-True ($Log -notmatch '--unregister') 'preview 触发了 unregister'
    }

    Invoke-Test 'destroy 无 Apply 不注销' {
        Reset-FakeLog $FakeLog
        $Args = $DestroyBase.Clone()
        $Args.ConfirmName = $DistroName
        $Thrown = $false
        try {
            Invoke-WithFakeLxss $DestroyScript $Args $DistroName $InstallPath
        }
        catch {
            $Thrown = $true
        }
        Assert-True $Thrown '提供确认但无 Apply 应返回非零'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--unregister') '无 Apply 触发了 unregister'
    }

    foreach ($WrongConfirmation in @($DistroName.ToLowerInvariant(), 'MiniOrangeOS-Dev-Test-Other')) {
        Invoke-Test "destroy 错误确认拒绝：$WrongConfirmation" {
            Reset-FakeLog $FakeLog
            $Args = $DestroyBase.Clone()
            $Args.Apply = $true
            $Args.ConfirmName = $WrongConfirmation
            $Thrown = $false
            try {
                Invoke-WithFakeLxss $DestroyScript $Args $DistroName $InstallPath
            }
            catch {
                $Thrown = $true
            }
            Assert-True $Thrown '错误确认应返回非零'
            Assert-True ((Read-FakeLog $FakeLog) -notmatch '--unregister') '错误确认触发了 unregister'
        }
    }

    Invoke-Test 'destroy 注册 BasePath 不匹配时拒绝' {
        Reset-FakeLog $FakeLog
        $Args = $DestroyBase.Clone()
        $Args.Apply = $true
        $Args.ConfirmName = $DistroName
        $Thrown = $false
        try {
            Invoke-WithFakeLxss $DestroyScript $Args $DistroName (Join-Path $AuthorizedRoot 'foreign')
        }
        catch {
            $Thrown = $true
        }
        Assert-True $Thrown 'BasePath 不匹配应返回非零'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--unregister') 'BasePath 不匹配触发了 unregister'
    }

    Invoke-Test 'destroy 注册名称不匹配时拒绝' {
        Reset-FakeLog $FakeLog
        $Args = $DestroyBase.Clone()
        $Args.Apply = $true
        $Args.ConfirmName = $DistroName
        $Thrown = $false
        try {
            Invoke-WithFakeLxss $DestroyScript $Args 'MiniOrangeOS-Dev-Test-Foreign' $InstallPath
        }
        catch {
            $Thrown = $true
        }
        Assert-True $Thrown '注册名称不匹配应返回非零'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--unregister') '注册名称不匹配触发了 unregister'
    }

    Invoke-Test 'destroy ReparsePoint 边界拒绝' {
        Reset-FakeLog $FakeLog
        $ReparseName = 'MiniOrangeOS-Dev-Test-Reparse'
        $ReparsePath = Join-Path (Join-Path $AuthorizedRoot 'drills') $ReparseName
        $OutsidePath = Join-Path $TemporaryRoot 'outside-reparse-target'
        [void][IO.Directory]::CreateDirectory($OutsidePath)
        $Junction = New-Item -ItemType Junction -Path $ReparsePath -Target $OutsidePath
        try {
            $env:FAKE_WSL_LIST = $ReparseName
            $Args = @{
                DistroName = $ReparseName
                AuthorizedRoot = $AuthorizedRoot
                WslExecutable = 'wsl.exe'
                Apply = $true
                ConfirmName = $ReparseName
            }
            $Thrown = $false
            try {
                Invoke-WithFakeLxss $DestroyScript $Args $ReparseName $ReparsePath
            }
            catch {
                $Thrown = $true
            }
            Assert-True $Thrown 'ReparsePoint 应返回非零'
            Assert-True ((Read-FakeLog $FakeLog) -notmatch '--unregister') 'ReparsePoint 触发了 unregister'
        }
        finally {
            if (Test-Path -LiteralPath $Junction.FullName) { Remove-Item -LiteralPath $Junction.FullName -Force }
            $env:FAKE_WSL_LIST = $DistroName
        }
    }

    Invoke-Test 'destroy 正确边界只注销精确名称（fake）' {
        Reset-FakeLog $FakeLog
        $Args = $DestroyBase.Clone()
        $Args.Apply = $true
        $Args.ConfirmName = $DistroName
        Invoke-WithFakeLxss $DestroyScript $Args $DistroName $InstallPath
        $Log = Read-FakeLog $FakeLog
        Assert-True ($Log -match "--unregister $([regex]::Escape($DistroName))") '未调用精确 unregister'
        Assert-True ($Log -notmatch '--shutdown') '禁止调用 --shutdown'
    }

    Invoke-Test 'create 下载哈希失败时不 import' {
        Reset-FakeLog $FakeLog
        Reset-FakeLog $DownloadLog
        $env:FAKE_WSL_LIST = 'Other-Distro'
        $Args = @{
            DistroName = 'MiniOrangeOS-Dev-Test-CreateHash'
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
            DownloadExecutable = $FakeDownload
        }
        $Thrown = $false
        try {
            Invoke-WithFakeLxss $CreateScript $Args $DistroName $InstallPath
        }
        catch {
            $Thrown = $true
        }
        Assert-True $Thrown '哈希失败应返回非零'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--import') '哈希失败触发了 import'
        Assert-True ((Read-FakeLog $DownloadLog) -ne '') '未到达 fake 下载后端'
        $PartialFiles = @(Get-ChildItem -LiteralPath $Downloads -Filter '*.partial')
        Assert-True ($PartialFiles.Count -eq 0) '哈希失败后遗留 partial 文件'
    }

    Invoke-Test 'create 已有发行版只验证 ownership 且不 import' {
        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName
        $Args = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
        }
        Invoke-WithFakeLxss $CreateScript $Args $DistroName $InstallPath
        $Log = Read-FakeLog $FakeLog
        Assert-True ($Log -notmatch '--import') '已有发行版仍触发 import'
        Assert-True ($Log -match '--provision-wsl-identity') '已有发行版未安全 provision identity record'
        Assert-True ($Log -match '--expected-distro') 'identity provision 未绑定精确发行版名'
        Assert-True ($Log -match '--registration-id') 'identity provision 未绑定 Lxss registration ID'
        Assert-True ($Log -match '--base-path-sha256') 'identity provision 未绑定 BasePath identity'
    }

    Invoke-Test '四个 WSL 入口拒绝非单路径段测试名称' {
        $InvalidNames = @(
            'MiniOrangeOS-Dev-Test-',
            'MiniOrangeOS-Dev-Test-.',
            'MiniOrangeOS-Dev-Test-..',
            'MiniOrangeOS-Dev-Test-a/b',
            'MiniOrangeOS-Dev-Test-a\b',
            'MiniOrangeOS-Dev-Test-a:b',
            'MiniOrangeOS-Dev-Test-a b',
            'MiniOrangeOS-Dev-Test-测试'
        )
        foreach ($InvalidName in $InvalidNames) {
            foreach ($ScriptPath in @($CreateScript, $EnterScript, $BackupScript, $DestroyScript)) {
                Reset-FakeLog $FakeLog
                $Arguments = @{
                    DistroName = $InvalidName
                    AuthorizedRoot = $AuthorizedRoot
                    WslExecutable = $FakeWsl
                }
                if ($ScriptPath -ceq $CreateScript) { $Arguments.SkipBootstrap = $true }
                $Thrown = $false
                try { & $ScriptPath @Arguments } catch { $Thrown = $true }
                Assert-True $Thrown "非法名称未拒绝：$InvalidName / $ScriptPath"
                $Log = Read-FakeLog $FakeLog
                Assert-True ($Log -notmatch '--import|--export|--terminate|--unregister|(?m)^-d ') "非法名称触发危险后端：$InvalidName"
            }
        }
    }

    Invoke-Test '所有入口拒绝缺失的 Lxss BasePath 末端' {
        $MissingName = 'MiniOrangeOS-Dev-Test-MissingBase'
        $MissingPath = Join-Path (Join-Path $AuthorizedRoot 'drills') $MissingName
        $env:FAKE_WSL_LIST = $MissingName
        foreach ($ScriptPath in @($CreateScript, $EnterScript, $BackupScript, $DestroyScript)) {
            Reset-FakeLog $FakeLog
            $Arguments = @{
                DistroName = $MissingName
                AuthorizedRoot = $AuthorizedRoot
                WslExecutable = $FakeWsl
            }
            if ($ScriptPath -ceq $CreateScript) { $Arguments.SkipBootstrap = $true }
            if ($ScriptPath -ceq $BackupScript) { $Arguments.ExportPath = Join-Path $Exports 'missing-base.tar' }
            $Thrown = $false
            try { Invoke-WithFakeLxss $ScriptPath $Arguments $MissingName $MissingPath } catch { $Thrown = $true }
            Assert-True $Thrown "缺失 BasePath 未拒绝：$ScriptPath"
            $Log = Read-FakeLog $FakeLog
            Assert-True ($Log -notmatch '--import|--export|--terminate|--unregister|(?m)^-d ') "缺失 BasePath 触发危险后端：$ScriptPath"
        }
        $env:FAKE_WSL_LIST = $DistroName
    }

    Invoke-Test '所有入口拒绝授权根外 BasePath 且不调用危险后端' {
        $ExternalName = 'MiniOrangeOS-Dev-Test-ExternalBase'
        $ExternalExpected = Join-Path (Join-Path $AuthorizedRoot 'drills') $ExternalName
        [void][IO.Directory]::CreateDirectory($ExternalExpected)
        $ExternalBase = Join-Path $TemporaryRoot 'external-registered-base'
        [void][IO.Directory]::CreateDirectory($ExternalBase)
        $env:FAKE_WSL_LIST = $ExternalName
        foreach ($ScriptPath in @($CreateScript, $EnterScript, $BackupScript, $DestroyScript)) {
            Reset-FakeLog $FakeLog
            $Arguments = @{
                DistroName = $ExternalName
                AuthorizedRoot = $AuthorizedRoot
                WslExecutable = $FakeWsl
            }
            if ($ScriptPath -ceq $CreateScript) { $Arguments.SkipBootstrap = $true }
            if ($ScriptPath -ceq $BackupScript) { $Arguments.ExportPath = Join-Path $Exports 'external-base.tar' }
            $Thrown = $false
            try { Invoke-WithFakeLxss $ScriptPath $Arguments $ExternalName $ExternalBase } catch { $Thrown = $true }
            Assert-True $Thrown "授权根外 BasePath 未拒绝：$ScriptPath"
            Assert-True ((Read-FakeLog $FakeLog) -notmatch '--import|--export|--terminate|--unregister|(?m)^-d ') "授权根外 BasePath 触发危险后端：$ScriptPath"
        }
        $env:FAKE_WSL_LIST = $DistroName
    }

    Invoke-Test 'create fake 下载、import 和两阶段 bootstrap 参数精确' {
        Reset-FakeLog $FakeLog
        Reset-FakeLog $DownloadLog
        $CreateName = 'MiniOrangeOS-Dev-Test-CreateImport'
        $CreatePath = Join-Path (Join-Path $AuthorizedRoot 'drills') $CreateName
        $env:FAKE_WSL_LIST = 'Other-Distro'
        $env:FAKE_FILE_HASH = '9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5'
        $Arguments = @{
            DistroName = $CreateName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
            DownloadExecutable = $FakeDownload
            Bootstrap = $true
        }
        try {
            Invoke-WithFakeLxss $CreateScript $Arguments $CreateName $CreatePath
        }
        finally {
            Remove-Item Env:FAKE_FILE_HASH -ErrorAction SilentlyContinue
        }
        $Log = Read-FakeLog $FakeLog
        Assert-True ($Log -match "--import\s+$([regex]::Escape($CreateName))") ("verified 下载后未 import 精确名称：$Log")
        Assert-True ($Log -match "-d $CreateName -u root -- bash .+ --system-only --target-user minios") ("缺少 root system-only bootstrap：$Log")
        Assert-True ($Log -match "-d $CreateName -u minios -- bash .+ --toolchain-only --target-user minios") ("缺少普通用户 toolchain-only bootstrap：$Log")
    }

    Invoke-Test 'create SkipBootstrap 可绑定且与 Bootstrap 冲突' {
        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName
        $Arguments = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
            Bootstrap = $true
            SkipBootstrap = $true
        }
        $Thrown = $false
        try { Invoke-WithFakeLxss $CreateScript $Arguments $DistroName $InstallPath } catch { $Thrown = $true }
        Assert-True $Thrown 'Bootstrap/SkipBootstrap 冲突未拒绝'
        Assert-True ((Read-FakeLog $FakeLog) -eq '') '冲突参数仍调用 WSL'

        $Arguments.Remove('Bootstrap')
        Invoke-WithFakeLxss $CreateScript $Arguments $DistroName $InstallPath
        Assert-True ((Read-FakeLog $FakeLog) -notmatch 'system-only|toolchain-only') 'SkipBootstrap 仍执行 bootstrap'
    }

    Invoke-Test 'backup 已有目标时不 export 或覆盖' {
        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName
        $ExistingExport = Join-Path $Exports 'existing.tar'
        [IO.File]::WriteAllText($ExistingExport, 'keep', [Text.Encoding]::UTF8)
        $Args = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
            ExportPath = $ExistingExport
        }
        $Thrown = $false
        try {
            Invoke-WithFakeLxss $BackupScript $Args $DistroName $InstallPath
        }
        catch {
            $Thrown = $true
        }
        Assert-True $Thrown '已有备份目标应返回非零'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--export') '已有目标触发了 export'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--terminate') '已有目标触发了 terminate'
        Assert-True ([IO.File]::ReadAllText($ExistingExport) -eq 'keep') '已有目标被覆盖'
    }

    Invoke-Test 'backup 校验 export partial、失败清理和移动竞态策略' {
        $env:FAKE_WSL_LIST = $DistroName
        $env:FAKE_WSL_JUNCTION_TARGET = Join-Path $TemporaryRoot 'backup-junction-target'
        foreach ($Mode in @('success', 'failure', 'empty', 'junction', 'move-fail')) {
            Reset-FakeLog $FakeLog
            $env:FAKE_WSL_EXPORT_MODE = $Mode
            $Export = Join-Path $Exports ("backup-$Mode.tar")
            $Arguments = @{
                DistroName = $DistroName
                AuthorizedRoot = $AuthorizedRoot
                WslExecutable = 'wsl.exe'
                ExportPath = $Export
            }
            $Thrown = $false
            try {
                Invoke-WithFakeLxss $BackupScript $Arguments $DistroName $InstallPath
            }
            catch {
                $Thrown = $true
            }
            if ($Mode -ceq 'success') {
                Assert-True (-not $Thrown) '合法非空 partial 应完成备份'
                Assert-True ((Test-Path -LiteralPath $Export -PathType Leaf) -and (Get-Item -LiteralPath $Export).Length -gt 0) '成功备份产物无效'
            }
            else {
                Assert-True $Thrown "异常 export 模式应失败：$Mode"
                Assert-True (-not (Test-Path -LiteralPath ($Export + '.partial'))) "异常后遗留 partial：$Mode"
            }
            if ($Mode -ceq 'move-fail') {
                Assert-True (Test-Path -LiteralPath $Export -PathType Container) '移动竞态创建的未知目标应保留'
            }
            if (Test-Path -LiteralPath $Export -PathType Leaf) { Remove-Item -LiteralPath $Export -Force }
            if (Test-Path -LiteralPath $Export -PathType Container) { Remove-Item -LiteralPath $Export -Force }
        }

        Reset-FakeLog $FakeLog
        $PreexistingExport = Join-Path $Exports 'preexisting-partial.tar'
        $PreexistingPartial = $PreexistingExport + '.partial'
        [IO.File]::WriteAllText($PreexistingPartial, 'unknown', [Text.Encoding]::UTF8)
        $Arguments = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = 'wsl.exe'
            ExportPath = $PreexistingExport
        }
        $Thrown = $false
        try { Invoke-WithFakeLxss $BackupScript $Arguments $DistroName $InstallPath } catch { $Thrown = $true }
        Assert-True $Thrown '预存 partial 应拒绝'
        Assert-True ([IO.File]::ReadAllText($PreexistingPartial) -eq 'unknown') '预存 partial 被改写'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--terminate|--export') '预存 partial 仍触发后端'
        Remove-Item -LiteralPath $PreexistingPartial -Force

        Reset-FakeLog $FakeLog
        $TerminateRaceExport = Join-Path $Exports 'terminate-race.tar'
        $TerminateRacePartial = $TerminateRaceExport + '.partial'
        $env:FAKE_WSL_TERMINATE_PARTIAL = $TerminateRacePartial
        $RaceArguments = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = 'wsl.exe'
            ExportPath = $TerminateRaceExport
        }
        $RaceThrown = $false
        try { Invoke-WithFakeLxss $BackupScript $RaceArguments $DistroName $InstallPath } catch { $RaceThrown = $true }
        Assert-True $RaceThrown 'terminate 后出现 partial 应拒绝'
        Assert-True ([IO.File]::ReadAllText($TerminateRacePartial) -eq 'concurrent-unknown') 'terminate 竞态 partial 被删除或改写'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--export') 'terminate 竞态仍触发 export'
        Remove-Item -LiteralPath $TerminateRacePartial -Force
        Remove-Item Env:FAKE_WSL_TERMINATE_PARTIAL -ErrorAction SilentlyContinue
        Remove-Item Env:FAKE_WSL_EXPORT_MODE -ErrorAction SilentlyContinue
        Remove-Item Env:FAKE_WSL_JUNCTION_TARGET -ErrorAction SilentlyContinue
    }

    Invoke-Test 'enter 只接受列表中的精确名称' {
        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName.ToLowerInvariant()
        $Thrown = $false
        try {
            & $EnterScript -DistroName $DistroName -AuthorizedRoot $AuthorizedRoot -WslExecutable $FakeWsl
        }
        catch {
            $Thrown = $true
        }
        Assert-True $Thrown '大小写不一致名称应被拒绝'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '(?m)^-d ') '错误名称进入了发行版'

        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName
        $EnterArgs = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
            Command = 'true'
        }
        Invoke-WithFakeLxss $EnterScript $EnterArgs $DistroName $InstallPath
        Assert-True ((Read-FakeLog $FakeLog) -match "-d $([regex]::Escape($DistroName)) -u minios") '未以 minios 用户进入精确名称的 fake 发行版'
    }

    Invoke-Test 'enter 单个命令字符串通过 bash -lc 精确保持' {
        $ArgumentsLog = Join-Path $TemporaryRoot 'wsl-arguments.log'
        $env:FAKE_WSL_JSON_LOG = $ArgumentsLog
        $env:FAKE_WSL_LIST = $DistroName
        $ComplexCommand = 'printf "%s" "$HOME"; printf " second value"'
        $Arguments = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWslArguments
            Command = @($ComplexCommand)
        }
        Invoke-WithFakeLxss $EnterScript $Arguments $DistroName $InstallPath
        $Lines = [IO.File]::ReadAllLines($ArgumentsLog)
        $LastCall = [Array]::LastIndexOf($Lines, 'CALL')
        Assert-True ($LastCall -ge 0) ("未记录 enter 调用：" + ($Lines -join '|'))
        $ActualArguments = @($Lines[($LastCall + 1)..($Lines.Length - 1)] | ForEach-Object {
            [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_.Substring(4)))
        })
        $ExpectedCommand = 'cd -- ' + (ConvertTo-MiniosShellLiteral $RepoWslPath) + ' && ' + $ComplexCommand
        $ExpectedArguments = @('-d', $DistroName, '-u', 'minios', '--', 'bash', '-lc', $ExpectedCommand)
        Assert-True (($ActualArguments -join "`0") -ceq ($ExpectedArguments -join "`0")) ("命令字符串边界发生变化：" + ($ActualArguments -join '|'))
        Remove-Item Env:FAKE_WSL_JSON_LOG -ErrorAction SilentlyContinue
    }

    Invoke-Test 'enter 拒绝含糊的多值 Command' {
        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName
        $Arguments = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = $FakeWsl
            Command = @('printf one', 'printf two')
        }
        $Thrown = $false
        try { Invoke-WithFakeLxss $EnterScript $Arguments $DistroName $InstallPath } catch { $Thrown = $true }
        Assert-True $Thrown '多值 Command 应被拒绝'
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '(?m)^-d ') '多值 Command 仍进入发行版'
    }

    Invoke-Test '已有 WSL1 注册项拒绝且不 bootstrap' {
        Reset-FakeLog $FakeLog
        $env:FAKE_WSL_LIST = $DistroName
        $Arguments = @{
            DistroName = $DistroName
            AuthorizedRoot = $AuthorizedRoot
            WslExecutable = 'wsl.exe'
            Bootstrap = $true
        }
        $Thrown = $false
        try { Invoke-WithFakeLxss $CreateScript $Arguments $DistroName $InstallPath 1 } catch { $Thrown = $true }
        Assert-True $Thrown 'WSL1 注册项应被拒绝'
        $Log = Read-FakeLog $FakeLog
        Assert-True ($Log -notmatch '--import|(?m)^-d ') 'WSL1 注册项仍触发 import/bootstrap'
    }

    Invoke-Test '真实 MiniOrangeOS-Dev 名称和 BasePath 只读验证' {
        $Names = @(& wsl.exe --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ }
        Assert-True (@($Names | Where-Object { $_ -ceq 'MiniOrangeOS-Dev' }).Count -eq 1) '真实发行版精确名称不存在'
        $LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
        $Key = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq 'MiniOrangeOS-Dev' } | Select-Object -First 1
        Assert-True ($null -ne $Key) '未找到真实发行版 Lxss 注册项'
        $BasePath = [IO.Path]::GetFullPath((Get-ItemProperty -LiteralPath $Key.PSPath).BasePath)
        $Version = (Get-ItemProperty -LiteralPath $Key.PSPath).Version
        $Expected = [IO.Path]::GetFullPath((Join-Path $ProductionAuthorizedRoot 'rootfs'))
        Assert-True ($BasePath -ceq $Expected) "真实 BasePath 不匹配：$BasePath"
        Assert-True ($Version -eq 2) "真实发行版不是 WSL2：Version=$Version"
        $Current = [IO.Path]::GetPathRoot($Expected)
        foreach ($Part in $Expected.Substring($Current.Length).Split([IO.Path]::DirectorySeparatorChar)) {
            if (-not $Part) { continue }
            $Current = Join-Path $Current $Part
            if (Test-Path -LiteralPath $Current) {
                $Item = Get-Item -LiteralPath $Current -Force
                Assert-True (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "真实路径包含 reparse point：$Current"
            }
        }
    }

    Invoke-Test '真实 enter 单条命令使用 bash -lc 执行' {
        & $EnterScript -Command 'test "$(printf enter-ok && printf second)" = enter-oksecond'
    }

    Invoke-Test '正式 WSL identity 与 Windows Lxss 注册绑定' {
        $LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
        $Keys = @(Get-ChildItem -LiteralPath $LxssRoot | Where-Object {
            (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq 'MiniOrangeOS-Dev'
        })
        Assert-True ($Keys.Count -eq 1) '正式发行版必须且只能有一个精确 Lxss 注册项'
        $Registration = Get-ItemProperty -LiteralPath $Keys[0].PSPath
        $RegistrationId = (Split-Path -Leaf $Keys[0].PSPath).ToLowerInvariant()
        Assert-True ($RegistrationId -cmatch '^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$') '正式 Lxss registration ID 格式不可信'
        Assert-True ($Registration.DistributionName -ceq 'MiniOrangeOS-Dev') '正式 Lxss 发行版名称不匹配'
        Assert-True ($Registration.Version -eq 2) '正式 Lxss 注册项不是 WSL2'

        $BasePath = [IO.Path]::GetFullPath($Registration.BasePath)
        $ExpectedBasePath = [IO.Path]::GetFullPath((Join-Path $ProductionAuthorizedRoot 'rootfs'))
        Assert-True ($BasePath -ceq $ExpectedBasePath) '正式 Lxss BasePath 不匹配'
        $Sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $BasePathBytes = [Text.Encoding]::UTF8.GetBytes($BasePath.ToLowerInvariant())
            $BasePathSha256 = ([BitConverter]::ToString($Sha256.ComputeHash($BasePathBytes))).Replace('-', '').ToLowerInvariant()
            $ExpectedRecord = "schema=1`ndistro=MiniOrangeOS-Dev`nregistration_id=$RegistrationId`nbase_path_sha256=$BasePathSha256`n"
            $ExpectedRecordBytes = [Text.Encoding]::UTF8.GetBytes($ExpectedRecord)
            $ExpectedRecordSha256 = ([BitConverter]::ToString($Sha256.ComputeHash($ExpectedRecordBytes))).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $Sha256.Dispose()
        }

        $PreviousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $IdentityScript = @'
set -euo pipefail
identity=/etc/miniorangeos/instance.identity
[[ -f "$identity" && ! -L "$identity" ]]
mapfile -t lines <"$identity"
[[ "${#lines[@]}" -eq 4 ]]
printf 'metadata=%s\n' "$(stat -c '%F|%U|%G|%a' -- "$identity")"
printf 'schema_line=%s\n' "${lines[0]}"
printf 'distro_line=%s\n' "${lines[1]}"
printf 'record_sha256=%s\n' "$(sha256sum -- "$identity" | cut -d ' ' -f 1)"
'@
            $IdentityOutput = @($IdentityScript | & wsl.exe -d MiniOrangeOS-Dev -u root -- bash -s -- 2>&1)
            $IdentityStatus = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousErrorAction
        }
        Assert-True ($IdentityStatus -eq 0) ("正式 identity 只读检查失败：" + ($IdentityOutput -join "`n"))
        $IdentityFacts = @{}
        foreach ($Line in $IdentityOutput) {
            $Separator = $Line.IndexOf('=')
            Assert-True ($Separator -gt 0) "正式 identity 检查返回了非法事实行：$Line"
            $IdentityFacts[$Line.Substring(0, $Separator)] = $Line.Substring($Separator + 1)
        }
        Assert-True ($IdentityFacts['metadata'] -ceq 'regular file|root|root|644') '正式 identity 必须是 root:root 0644 普通文件且非 symlink'
        Assert-True ($IdentityFacts['schema_line'] -ceq 'schema=1') '正式 identity schema 不匹配'
        Assert-True ($IdentityFacts['distro_line'] -ceq 'distro=MiniOrangeOS-Dev') '正式 identity distro 不匹配'
        Assert-True ($IdentityFacts['record_sha256'] -ceq $ExpectedRecordSha256) '正式 identity 未绑定已验证的 Lxss registration ID/BasePath'
    }

    Invoke-Test 'bootstrap fake 后端覆盖身份、降权状态写入与幂等' {
        $HarnessPath = Join-Path $TemporaryRoot 'bootstrap-fake-test.sh'
        $Harness = @'
#!/usr/bin/env bash
set -euo pipefail

source_script='__MINIOS_BOOTSTRAP_SOURCE__'
source_writer='__MINIOS_PACKAGE_WRITER_SOURCE__'
for token in MINIOS_WSL_CONF_PATH --prepare-package-state validate_isolation_identity validate_environment_root run_as_target; do
    grep -Fq -- "$token" "$source_script" || {
        printf 'RED missing bootstrap safety token: %s\n' "$token" >&2
        exit 99
    }
done

root=''
old_root="/tmp/minios-bootstrap-test-$$"
validate_test_root() {
    local canonical
    local metadata
    canonical="$(/usr/bin/realpath -e -- "$root")" || return 1
    [[ "$root" == "$canonical" \
        && "$canonical" =~ ^/tmp/minios-bootstrap-test-[A-Za-z0-9]{8}$ \
        && -d "$canonical" && ! -L "$canonical" ]] || return 1
    metadata="$(/usr/bin/stat -c '%F|%u|%a' -- "$canonical")" || return 1
    local item_type item_uid item_mode
    IFS='|' read -r item_type item_uid item_mode <<<"$metadata"
    [[ "$item_type" == directory && "$item_uid" == 0 \
        && "$item_mode" =~ ^[0-7]{3,4}$ \
        && $((8#$item_mode & 8#022)) -eq 0 ]]
}
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$root" ]]; then
        if validate_test_root; then
            /usr/bin/rm -rf -- "$root" || status=98
        else
            printf 'refusing unsafe bootstrap test cleanup: %s\n' "$root" >&2
            status=97
        fi
    fi
    if [[ -L "$old_root" && "$(/usr/bin/readlink -- "$old_root")" == '/' ]]; then
        /usr/bin/rm -f -- "$old_root" || status=96
    elif [[ -e "$old_root" || -L "$old_root" ]]; then
        printf 'refusing unknown predictable test path: %s\n' "$old_root" >&2
        status=95
    fi
    exit "$status"
}
trap cleanup EXIT
[[ ! -e "$old_root" && ! -L "$old_root" ]] || { printf 'predictable path already occupied\n' >&2; exit 1; }
/usr/bin/ln -s -- / "$old_root"
export TMPDIR="$old_root"
root="$(/usr/bin/mktemp -d /tmp/minios-bootstrap-test-XXXXXXXX)"
validate_test_root || { printf 'unsafe atomic bootstrap test root\n' >&2; exit 1; }
[[ "$root" != "$old_root" && -L "$old_root" ]] || { printf 'predictable symlink influenced mktemp\n' >&2; exit 1; }
unset TMPDIR
/usr/bin/rm -f -- "$old_root"
mkdir -p -- "$root/repo/environment/lib" "$root/repo/tools" "$root/fake" "$root/home/minios" "$root/logs"
chmod 0755 "$root" "$root/repo" "$root/repo/environment" "$root/repo/environment/lib" "$root/repo/tools" "$root/fake" "$root/home" "$root/logs"
cp -- "$source_script" "$root/repo/environment/bootstrap-inside.sh"
cp -- "$source_writer" "$root/repo/environment/lib/package_state_writer.py"
chmod 0755 "$root/repo/environment/bootstrap-inside.sh"
target_uid="$(/usr/bin/id -u minios)"
chown -R "minios:$target_uid" "$root/home/minios" "$root/logs"

cat >"$root/good-os-release" <<'EOF'
ID=ubuntu
VERSION_ID="24.04"
EOF
cat >"$root/bad-os-release" <<'EOF'
ID=debian
VERSION_ID="12"
EOF
chmod 0644 "$root/good-os-release" "$root/bad-os-release"

standard_os_root="$root/standard-os-root"
mkdir -p -- "$standard_os_root/etc" "$standard_os_root/usr/lib"
cp -- "$root/good-os-release" "$standard_os_root/usr/lib/os-release"
chmod 0755 "$standard_os_root" "$standard_os_root/etc" "$standard_os_root/usr" "$standard_os_root/usr/lib"
chmod 0644 "$standard_os_root/usr/lib/os-release"
ln -s -- ../usr/lib/os-release "$standard_os_root/etc/os-release"

wsl2_probe_root="$root/runtime-wsl2"
mkdir -p -- "$wsl2_probe_root/proc/sys/kernel" "$wsl2_probe_root/proc/sys/fs/binfmt_misc"
printf '%s\n' '6.6.87.2-microsoft-standard-WSL2' >"$wsl2_probe_root/proc/sys/kernel/osrelease"
printf '%s\n' 'Linux version 6.6.87.2-microsoft-standard-WSL2' >"$wsl2_probe_root/proc/version"
: >"$wsl2_probe_root/proc/sys/fs/binfmt_misc/WSLInterop"
chmod -R go-w -- "$wsl2_probe_root"

native_probe_root="$root/runtime-native"
mkdir -p -- "$native_probe_root/proc/sys/kernel" "$native_probe_root/proc/sys/fs/binfmt_misc"
printf '%s\n' '6.8.0-generic' >"$native_probe_root/proc/sys/kernel/osrelease"
printf '%s\n' 'Linux version 6.8.0-generic' >"$native_probe_root/proc/version"
chmod -R go-w -- "$native_probe_root"

container_probe_root="$root/runtime-container"
mkdir -p -- "$container_probe_root/proc/1" "$container_probe_root/run"
printf '%s\n' '0::/libpod-test.scope' >"$container_probe_root/proc/1/cgroup"
printf '%s\n' '1 0 0:1 / / rw - overlay overlay rw' >"$container_probe_root/proc/1/mountinfo"
: >"$container_probe_root/run/.containerenv"
chmod -R go-w -- "$container_probe_root"

bad_os_root="$root/bad-os-root"
mkdir -p -- "$bad_os_root/etc" "$bad_os_root/usr/lib"
cp -- "$root/bad-os-release" "$bad_os_root/usr/lib/os-release"
chmod 0755 "$bad_os_root" "$bad_os_root/etc" "$bad_os_root/usr" "$bad_os_root/usr/lib"
chmod 0644 "$bad_os_root/usr/lib/os-release"
ln -s -- ../usr/lib/os-release "$bad_os_root/etc/os-release"

cat >"$root/fake/getent" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == passwd && "$2" == minios ]]; then
    if [[ "${FAKE_MINIOS_MODE:-existing}" == missing && ! -f "${FAKE_USER_STATE:-/nonexistent}" ]]; then
        exit 2
    fi
    state="${FAKE_MINIOS_MODE:-existing}"
    [[ "$state" != missing ]] || state="$(cat -- "$FAKE_USER_STATE")"
    case "$state" in
        existing)
            printf 'minios:x:%s:%s::%s:/bin/bash\n' "$FAKE_TARGET_UID" "$FAKE_TARGET_UID" "$FAKE_TARGET_HOME"
            ;;
        success|symlink)
            printf 'minios:x:%s:%s::%s:/bin/bash\n' "$FAKE_TARGET_UID" "$FAKE_TARGET_UID" "$FAKE_EXPECTED_HOME"
            ;;
        uid0)
            printf 'minios:x:0:0::%s:/bin/bash\n' "$FAKE_EXPECTED_HOME"
            ;;
        wrong-home)
            printf 'minios:x:%s:%s::%s:/bin/bash\n' "$FAKE_TARGET_UID" "$FAKE_TARGET_UID" "$FAKE_WRONG_HOME"
            ;;
        *) exit 3 ;;
    esac
elif [[ "$1" == passwd && "$2" == evil ]]; then
    printf 'evil:x:0:0::%s:/bin/bash\n' "$FAKE_TARGET_HOME"
else
    exec /usr/bin/getent "$@"
fi
EOF
cat >"$root/fake/useradd" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'useradd' >>"$FAKE_USERADD_LOG"
printf ' <%s>' "$@" >>"$FAKE_USERADD_LOG"
printf '\n' >>"$FAKE_USERADD_LOG"
if [[ "$#" != 5 || "$1" != --create-home || "$2" != --shell \
    || "$3" != /bin/bash || "$4" != -- || "$5" != minios ]]; then
    exit 90
fi
case "${FAKE_USERADD_MODE:-success}" in
    failure) exit 9 ;;
    success)
        mkdir -- "$FAKE_EXPECTED_HOME"
        chown "minios:$FAKE_TARGET_UID" "$FAKE_EXPECTED_HOME"
        printf 'success\n' >"$FAKE_USER_STATE"
        ;;
    uid0)
        mkdir -- "$FAKE_EXPECTED_HOME"
        printf 'uid0\n' >"$FAKE_USER_STATE"
        ;;
    wrong-home)
        mkdir -- "$FAKE_WRONG_HOME"
        chown "minios:$FAKE_TARGET_UID" "$FAKE_WRONG_HOME"
        printf 'wrong-home\n' >"$FAKE_USER_STATE"
        ;;
    symlink)
        ln -s -- "$FAKE_SYMLINK_TARGET" "$FAKE_EXPECTED_HOME"
        printf 'symlink\n' >"$FAKE_USER_STATE"
        ;;
    *) exit 10 ;;
esac
EOF
cat >"$root/fake/apt-get" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'apt-get' >>"$FAKE_APT_LOG"
printf ' <%s>' "$@" >>"$FAKE_APT_LOG"
printf '\n' >>"$FAKE_APT_LOG"
if [[ -n "${FAKE_APT_BACKGROUND_PID_FILE:-}" \
    && ! -e "$FAKE_APT_BACKGROUND_PID_FILE" ]]; then
    (sleep 20 </dev/null >/dev/null 2>&1) &
    printf '%s\n' "$!" >"$FAKE_APT_BACKGROUND_PID_FILE"
fi
EOF
cat >"$root/fake/dpkg-query" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
package="${*: -1}"
printf '%s=1.fake\n' "$package"
EOF
cat >"$root/fake/runuser" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'runuser' >>"$FAKE_RUNUSER_LOG"
printf ' <%q>' "$@" >>"$FAKE_RUNUSER_LOG"
printf '\n' >>"$FAKE_RUNUSER_LOG"
exec /usr/sbin/runuser "$@"
EOF
cat >"$root/fake/sudo" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$root/repo/tools/build_toolchain.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'uid=%s\nroot=%s\nargs=%s\n' "$(id -u)" "$MINIOS_ENV_ROOT" "$*" >>"$FAKE_TOOL_LOG"
EOF
chmod 0755 "$root/fake/"* "$root/repo/tools/build_toolchain.sh"

apt_log="$root/apt.log"
runuser_log="$root/runuser.log"
tool_log="$root/logs/tool.log"
useradd_log="$root/useradd.log"
: >"$apt_log"
: >"$runuser_log"
: >"$tool_log"
: >"$useradd_log"
chmod 0666 "$apt_log" "$runuser_log" "$tool_log" "$useradd_log"

export PATH="$root/fake:/usr/sbin:/usr/bin:/sbin:/bin"
export FAKE_TARGET_UID="$target_uid"
export FAKE_TARGET_HOME="$root/home/minios"
export FAKE_APT_LOG="$apt_log"
export FAKE_RUNUSER_LOG="$runuser_log"
export FAKE_TOOL_LOG="$tool_log"
export FAKE_USERADD_LOG="$useradd_log"
export MINIOS_BOOTSTRAP_TEST_MODE=1
export MINIOS_BOOTSTRAP_TEST_ROOT="$root"
script="$root/repo/environment/bootstrap-inside.sh"
good_os="$standard_os_root/etc/os-release"
bad_os="$bad_os_root/etc/os-release"
wsl_conf="$root/wsl.conf"
identity_file="$root/instance.identity"

apt_lines() { wc -l <"$apt_log"; }
expect_gate_failure() {
    local description="$1"
    shift
    local before
    before="$(apt_lines)"
    rm -f -- "$wsl_conf"
    if "$@"; then
        printf 'expected gate failure: %s\n' "$description" >&2
        return 1
    fi
    [[ "$(apt_lines)" == "$before" ]] || { printf 'apt reached: %s\n' "$description" >&2; return 1; }
    [[ ! -e "$wsl_conf" ]] || { printf 'wsl.conf written: %s\n' "$description" >&2; return 1; }
}

common=(
    env
    "PATH=$PATH"
    "FAKE_TARGET_UID=$FAKE_TARGET_UID"
    "FAKE_TARGET_HOME=$FAKE_TARGET_HOME"
    "FAKE_APT_LOG=$FAKE_APT_LOG"
    "FAKE_RUNUSER_LOG=$FAKE_RUNUSER_LOG"
    "FAKE_TOOL_LOG=$FAKE_TOOL_LOG"
    "FAKE_USERADD_LOG=$FAKE_USERADD_LOG"
    MINIOS_BOOTSTRAP_TEST_MODE=1
    "MINIOS_BOOTSTRAP_TEST_ROOT=$root"
    "MINIOS_RUNTIME_PROBE_ROOT=$wsl2_probe_root"
    "MINIOS_WSL_IDENTITY_FILE=$identity_file"
    "MINIOS_WSL_CONF_PATH=$wsl_conf"
)

identity_args=(
    --provision-wsl-identity
    --expected-distro MiniOrangeOS-Dev
    --registration-id '{11111111-2222-3333-4444-555555555555}'
    --base-path-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
)
before_identity_apt="$(apt_lines)"
"${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "$script" "${identity_args[@]}"
[[ "$(apt_lines)" == "$before_identity_apt" ]] || { printf 'identity provision reached apt\n' >&2; exit 1; }
[[ "$(stat -c '%F|%u|%a' "$identity_file")" == 'regular file|0|644' ]] || { printf 'identity metadata mismatch\n' >&2; exit 1; }
identity_before="$(sha256sum "$identity_file")"
"${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "$script" "${identity_args[@]}"
[[ "$(sha256sum "$identity_file")" == "$identity_before" ]] || { printf 'identity idempotency mismatch\n' >&2; exit 1; }
if "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "$script" --provision-wsl-identity --expected-distro MiniOrangeOS-Dev \
    --registration-id '{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}' \
    --base-path-sha256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; then
    printf 'mismatched identity was overwritten\n' >&2
    exit 1
fi
[[ "$(sha256sum "$identity_file")" == "$identity_before" ]] || { printf 'mismatched provision changed identity\n' >&2; exit 1; }
expect_gate_failure wsl2-spoof-missing-record "${common[@]}" \
    MINIOS_WSL_IDENTITY_FILE="$root/missing.identity" \
    MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev-Test-Foreign \
    "$script" --system-only
mismatched_identity="$root/mismatched.identity"
sed 's/^distro=.*/distro=MiniOrangeOS-Dev-Test-Foreign/' "$identity_file" >"$mismatched_identity"
chmod 0644 "$mismatched_identity"
expect_gate_failure wsl2-spoof-mismatched-record "${common[@]}" \
    MINIOS_WSL_IDENTITY_FILE="$mismatched_identity" \
    MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "$script" --system-only

create_os_case() {
    local name="$1"
    os_case_root="$root/os-case-$name"
    mkdir -p -- "$os_case_root/etc" "$os_case_root/usr/lib"
    cp -- "$root/good-os-release" "$os_case_root/usr/lib/os-release"
    chmod 0755 "$os_case_root" "$os_case_root/etc" "$os_case_root/usr" "$os_case_root/usr/lib"
    chmod 0644 "$os_case_root/usr/lib/os-release"
    ln -s -- ../usr/lib/os-release "$os_case_root/etc/os-release"
    os_case_path="$os_case_root/etc/os-release"
}
expect_os_gate_failure() {
    local description="$1"
    expect_gate_failure "$description" "${common[@]}" \
        "MINIOS_OS_RELEASE_FILE=$os_case_path" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
        "$script" --system-only
}

create_os_case absolute-link
rm -f -- "$os_case_path"
ln -s -- "$os_case_root/usr/lib/os-release" "$os_case_path"
expect_os_gate_failure os-release-absolute-link

os_case_path="$root/good-os-release"
expect_os_gate_failure os-release-arbitrary-test-override

create_os_case escaping-link
rm -f -- "$os_case_path"
ln -s -- ../../../../etc/os-release "$os_case_path"
expect_os_gate_failure os-release-escaping-link

create_os_case nonexact-link
rm -f -- "$os_case_path"
ln -s -- ../usr/lib/./os-release "$os_case_path"
expect_os_gate_failure os-release-nonexact-link

create_os_case chained-target
mv -- "$os_case_root/usr/lib/os-release" "$os_case_root/usr/lib/os-release.real"
ln -s -- os-release.real "$os_case_root/usr/lib/os-release"
expect_os_gate_failure os-release-chained-target

create_os_case missing-target
rm -f -- "$os_case_root/usr/lib/os-release"
expect_os_gate_failure os-release-missing-target

create_os_case directory-target
rm -f -- "$os_case_root/usr/lib/os-release"
mkdir -- "$os_case_root/usr/lib/os-release"
expect_os_gate_failure os-release-directory-target

create_os_case writable-target
chmod 0666 "$os_case_root/usr/lib/os-release"
expect_os_gate_failure os-release-writable-target

create_os_case nonroot-target
chown "minios:$target_uid" "$os_case_root/usr/lib/os-release"
expect_os_gate_failure os-release-nonroot-target

create_os_case symlink-etc-parent
rm -f -- "$os_case_path"
rmdir -- "$os_case_root/etc"
mkdir -- "$os_case_root/real-etc"
chmod 0755 "$os_case_root/real-etc"
ln -s -- ../usr/lib/os-release "$os_case_root/real-etc/os-release"
ln -s -- real-etc "$os_case_root/etc"
expect_os_gate_failure os-release-symlink-etc-parent

create_os_case symlink-lib-parent
mkdir -- "$os_case_root/real-lib"
chmod 0755 "$os_case_root/real-lib"
mv -- "$os_case_root/usr/lib/os-release" "$os_case_root/real-lib/os-release"
rmdir -- "$os_case_root/usr/lib"
ln -s -- ../real-lib "$os_case_root/usr/lib"
expect_os_gate_failure os-release-symlink-lib-parent

create_os_case writable-etc-parent
chmod 0777 "$os_case_root/etc"
expect_os_gate_failure os-release-writable-etc-parent

create_os_case writable-lib-parent
chmod 0777 "$os_case_root/usr/lib"
expect_os_gate_failure os-release-writable-lib-parent

create_os_case nonroot-link
chown -h "minios:$target_uid" "$os_case_path"
expect_os_gate_failure os-release-nonroot-link

expect_gate_failure wrong-os "${common[@]}" MINIOS_OS_RELEASE_FILE="$bad_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev "$script" --system-only
expect_gate_failure missing-identity "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME= MINIOS_CONTAINER= "$script" --system-only
expect_gate_failure wrong-distro "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=Ubuntu "$script" --system-only
expect_gate_failure native-wsl-name-spoof "${common[@]}" MINIOS_RUNTIME_PROBE_ROOT="$native_probe_root" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev "$script" --system-only
expect_gate_failure container-env-spoof "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME= MINIOS_CONTAINER=1 "$script" --system-only
expect_gate_failure root-target "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev "$script" --system-only --target-user root
expect_gate_failure uid0-alias "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev "$script" --system-only --target-user evil
expect_gate_failure wsl-conf-traversal "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev MINIOS_WSL_CONF_PATH="$root/logs/../protected-wsl-conf" "$script" --system-only

protected="$root/protected"
mkdir -p -- "$protected"
printf 'protected\n' >"$protected/sentinel"
chmod 0600 "$protected/sentinel"
protected_before="$(stat -c '%u|%a|%s' "$protected/sentinel")|$(cat "$protected/sentinel")"
ln -s -- "$protected" "$root/home/minios/link"
expect_gate_failure symlink-env "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev MINIOS_ENV_ROOT="$root/home/minios/link/env" "$script" --system-only
protected_after="$(stat -c '%u|%a|%s' "$protected/sentinel")|$(cat "$protected/sentinel")"
[[ "$protected_before" == "$protected_after" ]] || { printf 'protected target changed\n' >&2; exit 1; }

prepare_missing_case() {
    local case_name="$1"
    missing_parent="$root/missing-$case_name"
    missing_home="$missing_parent/minios"
    missing_wrong_home="$missing_parent/wrong-home"
    missing_state="$root/state-$case_name"
    mkdir -- "$missing_parent"
    chmod 0755 "$missing_parent"
    rm -f -- "$missing_state"
}
missing_command() {
    local useradd_mode="$1"
    shift
    "${common[@]}" \
        FAKE_MINIOS_MODE=missing \
        "FAKE_USER_STATE=$missing_state" \
        "FAKE_EXPECTED_HOME=$missing_home" \
        "FAKE_WRONG_HOME=$missing_wrong_home" \
        "FAKE_SYMLINK_TARGET=$protected" \
        "FAKE_USERADD_MODE=$useradd_mode" \
        "MINIOS_USERADD_EXECUTABLE=$root/fake/useradd" \
        "MINIOS_EXPECTED_MINIOS_HOME=$missing_home" \
        MINIOS_OS_RELEASE_FILE="$good_os" \
        WSL_DISTRO_NAME=MiniOrangeOS-Dev \
        "MINIOS_ENV_ROOT=$missing_home/environment" \
        "$@"
}

prepare_missing_case success
missing_apt_before="$(apt_lines)"
missing_useradd_before="$(wc -l <"$useradd_log")"
missing_command success "$script" --system-only
[[ "$(apt_lines)" == "$((missing_apt_before + 2))" ]] || { printf 'missing user success did not run exact apt phases\n' >&2; exit 1; }
[[ "$(wc -l <"$useradd_log")" == "$((missing_useradd_before + 1))" ]] || { printf 'useradd invocation count mismatch\n' >&2; exit 1; }
tail -n 1 "$useradd_log" | grep -Fqx -- 'useradd <--create-home> <--shell> </bin/bash> <--> <minios>'
[[ -s "$missing_home/environment/state/apt-packages.lock" ]]
/usr/sbin/runuser -u minios -- env \
    "PATH=$PATH" "FAKE_TARGET_UID=$target_uid" "FAKE_TARGET_HOME=$root/home/minios" \
    "FAKE_MINIOS_MODE=missing" "FAKE_USER_STATE=$missing_state" \
    "FAKE_EXPECTED_HOME=$missing_home" "FAKE_WRONG_HOME=$missing_wrong_home" \
    "FAKE_TOOL_LOG=$tool_log" MINIOS_BOOTSTRAP_TEST_MODE=1 \
    "MINIOS_BOOTSTRAP_TEST_ROOT=$root" "MINIOS_RUNTIME_PROBE_ROOT=$wsl2_probe_root" "MINIOS_WSL_IDENTITY_FILE=$identity_file" "MINIOS_OS_RELEASE_FILE=$good_os" \
    WSL_DISTRO_NAME=MiniOrangeOS-Dev "MINIOS_ENV_ROOT=$missing_home/environment" \
    "$script" --toolchain-only --target-user minios
grep -Fq -- "root=$missing_home/environment" "$tool_log"

for failure_mode in failure uid0 wrong-home symlink; do
    prepare_missing_case "$failure_mode"
    before_apt="$(apt_lines)"
    before_useradd="$(wc -l <"$useradd_log")"
    if missing_command "$failure_mode" "$script" --system-only; then
        printf 'missing user failure mode unexpectedly passed: %s\n' "$failure_mode" >&2
        exit 1
    fi
    [[ "$(apt_lines)" == "$before_apt" ]] || { printf 'apt reached after useradd failure: %s\n' "$failure_mode" >&2; exit 1; }
    [[ "$(wc -l <"$useradd_log")" == "$((before_useradd + 1))" ]] || { printf 'useradd count mismatch: %s\n' "$failure_mode" >&2; exit 1; }
done

prepare_missing_case identity-first
before_useradd="$(wc -l <"$useradd_log")"
expect_gate_failure missing-user-wrong-os \
    "${common[@]}" FAKE_MINIOS_MODE=missing "FAKE_USER_STATE=$missing_state" \
    "FAKE_EXPECTED_HOME=$missing_home" "FAKE_USERADD_MODE=success" \
    "MINIOS_USERADD_EXECUTABLE=$root/fake/useradd" "MINIOS_EXPECTED_MINIOS_HOME=$missing_home" \
    MINIOS_OS_RELEASE_FILE="$bad_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "$script" --system-only
[[ "$(wc -l <"$useradd_log")" == "$before_useradd" ]] || { printf 'useradd ran before OS gate\n' >&2; exit 1; }

before_useradd="$(wc -l <"$useradd_log")"
expect_gate_failure other-missing-user \
    "${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "$script" --system-only --target-user minios_missing_other
expect_gate_failure container-missing-user \
    "${common[@]}" FAKE_MINIOS_MODE=missing "FAKE_USER_STATE=$missing_state" \
    MINIOS_OS_RELEASE_FILE="$good_os" MINIOS_CONTAINER=1 \
    "$script" --system-only
if /usr/sbin/runuser -u minios -- env \
    "PATH=$PATH" "FAKE_TARGET_UID=$target_uid" FAKE_MINIOS_MODE=missing \
    "FAKE_USER_STATE=$missing_state" MINIOS_BOOTSTRAP_TEST_MODE=1 \
    "MINIOS_BOOTSTRAP_TEST_ROOT=$root" "MINIOS_RUNTIME_PROBE_ROOT=$wsl2_probe_root" "MINIOS_WSL_IDENTITY_FILE=$identity_file" "MINIOS_OS_RELEASE_FILE=$good_os" \
    WSL_DISTRO_NAME=MiniOrangeOS-Dev "$script" --toolchain-only --target-user minios; then
    printf 'toolchain-only created missing user\n' >&2
    exit 1
fi
[[ "$(wc -l <"$useradd_log")" == "$before_useradd" ]] || { printf 'forbidden phase invoked useradd\n' >&2; exit 1; }
printf 'checkpoint=missing-user-gates\n'

create_env_case() {
    local name="$1"
    env_case_parent="$root/home/minios/env-case-$name"
    env_case_middle="$env_case_parent/middle"
    env_case_final="$env_case_middle/final"
    mkdir -p -- "$env_case_final"
    chown -R "minios:$target_uid" "$env_case_parent"
    chmod 0755 "$env_case_parent" "$env_case_middle" "$env_case_final"
}
expect_env_gate_failure() {
    local description="$1"
    expect_gate_failure "$description" "${common[@]}" \
        MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
        "MINIOS_ENV_ROOT=$env_case_final" "$script" --system-only
}

create_env_case root-intermediate-0775
chown root:root "$env_case_middle"
chmod 0775 "$env_case_middle"
expect_env_gate_failure root-intermediate-0775

create_env_case root-intermediate-0777
chown root:root "$env_case_middle"
chmod 0777 "$env_case_middle"
expect_env_gate_failure root-intermediate-0777

create_env_case other-owner-intermediate
nobody_uid="$(id -u nobody)"
chown "$nobody_uid:$nobody_uid" "$env_case_middle"
expect_env_gate_failure other-owner-intermediate

create_env_case target-writable-intermediate
chmod 0775 "$env_case_middle"
expect_env_gate_failure target-writable-intermediate

create_env_case file-intermediate
rmdir -- "$env_case_final" "$env_case_middle"
printf 'not-directory\n' >"$env_case_middle"
chown "minios:$target_uid" "$env_case_middle"
expect_env_gate_failure file-intermediate

create_env_case root-owned-final
chown root:root "$env_case_final"
expect_env_gate_failure root-owned-final

create_env_case writable-final
chmod 0775 "$env_case_final"
expect_env_gate_failure writable-final

create_env_case symlink-final
rmdir -- "$env_case_final"
ln -s -- "$protected" "$env_case_final"
expect_env_gate_failure symlink-final

lexical_real="$root/home/minios/lexical-real"
lexical_real_final="$lexical_real/final"
mkdir -p -- "$lexical_real_final"
chown -R "minios:$target_uid" "$lexical_real"
chmod 0755 "$lexical_real" "$lexical_real_final"
ln -s -- lexical-real "$root/home/minios/lexical-alias"
env_case_final="$root/home/minios/lexical-alias/final"
expect_env_gate_failure same-home-intermediate-symlink

lexical_link_parent="$root/home/minios/lexical-link-parent"
mkdir -- "$lexical_link_parent"
chown "minios:$target_uid" "$lexical_link_parent"
chmod 0755 "$lexical_link_parent"
ln -s -- ../lexical-real/final "$lexical_link_parent/final"
env_case_final="$lexical_link_parent/final"
expect_env_gate_failure same-home-final-symlink

env_case_final="$root/home/minios/lexical-real/../lexical-real/final"
expect_env_gate_failure noncanonical-dot-segment
env_case_final='relative/environment-root'
expect_env_gate_failure relative-environment-root
env_case_final=''
expect_env_gate_failure empty-environment-root

chmod 0775 "$root/home/minios"
env_case_final="$root/home/minios/home-mode-final"
expect_env_gate_failure writable-target-home
chmod 0755 "$root/home/minios"

protected_after_ancestor_cases="$(stat -c '%u|%a|%s' "$protected/sentinel")|$(cat "$protected/sentinel")"
[[ "$protected_before" == "$protected_after_ancestor_cases" ]] || { printf 'ancestor cases changed protected target\n' >&2; exit 1; }

fresh_environment_root="$root/home/minios/.local/share/miniorangeos-dev"
/usr/sbin/runuser -u minios -- env \
    "PATH=$PATH" "FAKE_TARGET_UID=$target_uid" "FAKE_TARGET_HOME=$root/home/minios" \
    MINIOS_BOOTSTRAP_TEST_MODE=1 "MINIOS_BOOTSTRAP_TEST_ROOT=$root" \
    "MINIOS_RUNTIME_PROBE_ROOT=$wsl2_probe_root" "MINIOS_WSL_IDENTITY_FILE=$identity_file" \
    "MINIOS_OS_RELEASE_FILE=$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "MINIOS_ENV_ROOT=$fresh_environment_root" \
    "$script" --prepare-package-state --target-user minios
for created_directory in \
    "$root/home/minios/.local" \
    "$root/home/minios/.local/share" \
    "$fresh_environment_root" \
    "$fresh_environment_root/state"; do
    [[ "$(stat -c '%F|%u|%a' -- "$created_directory")" == "directory|$target_uid|755" ]] \
        || { printf 'fresh environment directory metadata mismatch: %s\n' "$created_directory" >&2; exit 1; }
done
rm -rf -- "$root/home/minios/.local"
printf 'checkpoint=fresh-environment-root\n'

environment_root="$root/home/minios/.local/share/miniorangeos-dev"
mkdir -p -- "$environment_root"
chown root:root "$root/home/minios/.local" "$root/home/minios/.local/share"
chmod 0755 "$root/home/minios/.local" "$root/home/minios/.local/share"
chown "minios:$target_uid" "$environment_root"
chmod 0755 "$environment_root"

state_path="$environment_root/state"
exercise_state_failure() {
    local description="$1"
    shift
    rm -rf -- "$state_path"
    "$@"
    expect_gate_failure "$description" "${positive[@]}" "$script" --system-only
}
positive=(
    "${common[@]}"
    "MINIOS_OS_RELEASE_FILE=$good_os"
    WSL_DISTRO_NAME=MiniOrangeOS-Dev
    "MINIOS_ENV_ROOT=$environment_root"
)
exercise_state_failure state-symlink ln -s -- "$protected" "$state_path"
exercise_state_failure state-nondirectory sh -c 'printf bad >"$1"' sh "$state_path"
exercise_state_failure state-wrong-owner sh -c 'mkdir -- "$1"; chown root:root "$1"; chmod 0755 "$1"' sh "$state_path"
exercise_state_failure state-writable sh -c 'mkdir -- "$1"; chown "minios:$2" "$1"; chmod 0775 "$1"' sh "$state_path" "$target_uid"
exercise_state_failure lock-symlink sh -c 'mkdir -- "$1"; chown "minios:$2" "$1"; ln -s -- "$3" "$1/apt-packages.lock"' sh "$state_path" "$target_uid" "$protected/sentinel"
exercise_state_failure partial-symlink sh -c 'mkdir -- "$1"; chown "minios:$2" "$1"; ln -s -- "$3" "$1/apt-packages.lock.partial.attack"' sh "$state_path" "$target_uid" "$protected/sentinel"
rm -rf -- "$state_path"

for race_phase in before-open after-open after-partial; do
    mkdir -- "$state_path"
    chown "minios:$target_uid" "$state_path"
    chmod 0755 "$state_path"
    race_original="$environment_root/state-original-$race_phase"
    race_apt_before="$(apt_lines)"
    if "${positive[@]}" MINIOS_PACKAGE_STATE_RACE_PHASE="$race_phase" \
        "FAKE_RACE_STATE=$state_path" "FAKE_RACE_ORIGINAL=$race_original" \
        "FAKE_RACE_OUTSIDE=$protected" "$script" --system-only; then
        printf 'state parent race unexpectedly passed: %s\n' "$race_phase" >&2
        exit 1
    fi
    [[ "$(apt_lines)" == "$((race_apt_before + 2))" ]] || { printf 'race did not occur after apt phases: %s\n' "$race_phase" >&2; exit 1; }
    [[ -L "$state_path" && "$(readlink -- "$state_path")" == "$protected" ]] || { printf 'race did not replace pathname: %s\n' "$race_phase" >&2; exit 1; }
    [[ ! -e "$protected/apt-packages.lock" && ! -L "$protected/apt-packages.lock" ]] || { printf 'race wrote external final lock: %s\n' "$race_phase" >&2; exit 1; }
    [[ -z "$(find "$protected" -maxdepth 1 -name 'apt-packages.lock.partial.*' -print -quit)" ]] || { printf 'race wrote external partial: %s\n' "$race_phase" >&2; exit 1; }
    [[ -z "$(find "$race_original" -maxdepth 1 -name 'apt-packages.lock.partial.*' -print -quit)" ]] || { printf 'anchored partial cleanup failed: %s\n' "$race_phase" >&2; exit 1; }
    [[ "$(stat -c '%u|%a' "$race_original")" == "$target_uid|755" ]] || { printf 'anchored state metadata was not restored: %s\n' "$race_phase" >&2; exit 1; }
    rm -f -- "$state_path"
    rm -rf -- "$race_original"
done
for helper_failure in signal-after-create replace-partial; do
    mkdir -- "$state_path"
    chown "minios:$target_uid" "$state_path"
    chmod 0755 "$state_path"
    helper_original="$environment_root/state-unused-$helper_failure"
    helper_apt_before="$(apt_lines)"
    if "${positive[@]}" MINIOS_PACKAGE_STATE_RACE_PHASE="$helper_failure" \
        "FAKE_RACE_STATE=$state_path" "FAKE_RACE_ORIGINAL=$helper_original" \
        "FAKE_RACE_OUTSIDE=$protected" "$script" --system-only; then
        printf 'helper failure probe unexpectedly passed: %s\n' "$helper_failure" >&2
        exit 1
    fi
    [[ "$(apt_lines)" == "$((helper_apt_before + 2))" ]] || { printf 'helper failure did not run after apt: %s\n' "$helper_failure" >&2; exit 1; }
    [[ -d "$state_path" && ! -L "$state_path" ]] || { printf 'helper failure replaced state path: %s\n' "$helper_failure" >&2; exit 1; }
    [[ "$(stat -c '%u|%a' "$state_path")" == "$target_uid|755" ]] || { printf 'helper failure did not restore state metadata: %s\n' "$helper_failure" >&2; exit 1; }
    [[ ! -e "$state_path/apt-packages.lock" && ! -L "$state_path/apt-packages.lock" ]] || { printf 'helper failure committed final lock: %s\n' "$helper_failure" >&2; exit 1; }
    [[ -z "$(find "$state_path" -maxdepth 1 -name 'apt-packages.lock.partial.*' -print -quit)" ]] || { printf 'helper failure left partial: %s\n' "$helper_failure" >&2; exit 1; }
    rm -rf -- "$state_path"
done
for crash_phase in kill-after-restrict kill-after-partial; do
    mkdir -- "$state_path"
    chown "minios:$target_uid" "$state_path"
    chmod 0755 "$state_path"
    crash_original="$environment_root/state-unused-$crash_phase"
    if "${positive[@]}" MINIOS_PACKAGE_STATE_RACE_PHASE="$crash_phase" \
        "FAKE_RACE_STATE=$state_path" "FAKE_RACE_ORIGINAL=$crash_original" \
        "FAKE_RACE_OUTSIDE=$protected" "$script" --system-only; then
        printf 'SIGKILL crash probe unexpectedly passed: %s\n' "$crash_phase" >&2
        exit 1
    fi
    [[ "$(stat -c '%u|%a' "$state_path")" == '0|700' ]] || { printf 'SIGKILL did not leave exact recoverable residue: %s\n' "$crash_phase" >&2; exit 1; }
    if [[ "$crash_phase" == kill-after-partial ]]; then
        [[ -n "$(find "$state_path" -maxdepth 1 -type f -name 'apt-packages.lock.partial.*' -print -quit)" ]] || { printf 'partial crash residue missing\n' >&2; exit 1; }
    fi
    /usr/bin/timeout 8 "${positive[@]}" "$script" --system-only
    [[ "$(stat -c '%u|%a' "$state_path")" == "$target_uid|755" ]] || { printf 'crash recovery did not restore state metadata: %s\n' "$crash_phase" >&2; exit 1; }
    [[ -s "$state_path/apt-packages.lock" && ! -L "$state_path/apt-packages.lock" ]] || { printf 'crash recovery retry did not commit lock: %s\n' "$crash_phase" >&2; exit 1; }
    [[ -z "$(find "$state_path" -maxdepth 1 -name 'apt-packages.lock.partial.*' -print -quit)" ]] || { printf 'crash recovery left partial: %s\n' "$crash_phase" >&2; exit 1; }
    rm -rf -- "$state_path"
done
mkdir -- "$state_path"
chmod 0700 "$state_path"
ln -s -- "$protected/sentinel" "$state_path/apt-packages.lock.partial.123.0123456789abcdef"
recovery_apt_before="$(apt_lines)"
if "${positive[@]}" "$script" --system-only; then
    printf 'root residue symlink unexpectedly recovered\n' >&2
    exit 1
fi
[[ "$(apt_lines)" == "$recovery_apt_before" ]] || { printf 'malicious symlink residue reached apt\n' >&2; exit 1; }
[[ -L "$state_path/apt-packages.lock.partial.123.0123456789abcdef" ]] || { printf 'malicious symlink residue was changed\n' >&2; exit 1; }
rm -rf -- "$state_path"
mkdir -- "$state_path"
chmod 0700 "$state_path"
foreign_partial="$state_path/apt-packages.lock.partial.456.fedcba9876543210"
printf 'foreign\n' >"$foreign_partial"
if "${positive[@]}" "$script" --system-only; then
    printf 'foreign root residue unexpectedly recovered\n' >&2
    exit 1
fi
[[ "$(apt_lines)" == "$recovery_apt_before" ]] || { printf 'foreign residue reached apt\n' >&2; exit 1; }
[[ -f "$foreign_partial" && "$(stat -c '%u|%a' "$foreign_partial")" == '0|644' ]] || { printf 'foreign residue was changed\n' >&2; exit 1; }
rm -rf -- "$state_path"
positive_apt_before="$(apt_lines)"
apt_background_pid_file="$root/apt-background.pid"
"${positive[@]}" FAKE_APT_BACKGROUND_PID_FILE="$apt_background_pid_file" "$script" --system-only
apt_background_pid="$(cat -- "$apt_background_pid_file")"
kill -0 "$apt_background_pid" || { printf 'apt background inheritance probe did not remain alive\n' >&2; exit 1; }
lock="$environment_root/state/apt-packages.lock"
[[ -s "$lock" && ! -L "$lock" ]] || { printf 'package lock missing\n' >&2; exit 1; }
[[ "$(stat -c %u "$lock")" == "$target_uid" ]] || { printf 'package lock owner mismatch\n' >&2; exit 1; }
[[ "$(stat -c %a "$lock")" == 644 ]] || { printf 'package lock mode mismatch\n' >&2; exit 1; }
[[ "$(stat -c '%F|%u|%a' "$environment_root/state")" == "directory|$target_uid|755" ]] || { printf 'state metadata mismatch\n' >&2; exit 1; }
approved_packages=(build-essential bison flex libgmp-dev libmpfr-dev libmpc-dev texinfo nasm qemu-system-x86 qemu-utils gdb python3 python3-venv ca-certificates curl xz-utils sudo)
[[ "$(wc -l <"$lock")" == "${#approved_packages[@]}" ]] || { printf 'package lock line count mismatch\n' >&2; exit 1; }
for package in "${approved_packages[@]}"; do
    grep -Fqx -- "$package=1.fake" "$lock"
done
[[ -z "$(find "$environment_root/state" -maxdepth 1 -name 'apt-packages.lock.partial.*' -print -quit)" ]]
lock_before="$(sha256sum "$lock")"
/usr/bin/timeout 8 "${positive[@]}" "$script" --system-only
[[ "$(sha256sum "$lock")" == "$lock_before" ]] || { printf 'idempotent lock mismatch\n' >&2; exit 1; }
[[ "$(apt_lines)" == "$((positive_apt_before + 4))" ]] || { printf 'approved apt phases missing\n' >&2; exit 1; }
kill "$apt_background_pid" 2>/dev/null || true
wait "$apt_background_pid" 2>/dev/null || true
printf 'checkpoint=lock-idempotent\n'
grep -Fq -- '<install>' "$apt_log"
grep -Fq -- '<build-essential>' "$apt_log"
grep -Fq -- '<MINIOS_ENV_ROOT=' "$runuser_log"
grep -Fq -- '--prepare-package-state' "$runuser_log"
grep -Fq -- 'default=minios' "$wsl_conf"
printf 'checkpoint=system-evidence\n'

missing_final_parent="$root/home/minios/root-owned-missing-final"
missing_final_root="$missing_final_parent/environment"
mkdir -- "$missing_final_parent"
chown root:root "$missing_final_parent"
chmod 0755 "$missing_final_parent"
missing_final_apt_before="$(apt_lines)"
if missing_final_output="$("${common[@]}" MINIOS_OS_RELEASE_FILE="$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    MINIOS_ENV_ROOT="$missing_final_root" "$script" --system-only 2>&1)"; then
    printf 'root-owned ancestor with missing final unexpectedly passed\n' >&2
    exit 1
fi
[[ "$missing_final_output" == *'Permission denied'* || "$missing_final_output" == *'FAIL'* ]] || { printf 'missing final failure lacked clear diagnostic: %s\n' "$missing_final_output" >&2; exit 1; }
[[ "$(apt_lines)" == "$missing_final_apt_before" ]] || { printf 'missing final reached apt before state preflight\n' >&2; exit 1; }
[[ ! -e "$missing_final_root" && ! -L "$missing_final_root" ]] || { printf 'root wrote missing user environment root\n' >&2; exit 1; }
printf 'checkpoint=root-ancestor-missing-final\n'

/usr/sbin/runuser -u minios -- env \
    "PATH=$PATH" "FAKE_TARGET_UID=$target_uid" "FAKE_TARGET_HOME=$root/home/minios" \
    "FAKE_TOOL_LOG=$tool_log" MINIOS_BOOTSTRAP_TEST_MODE=1 \
    "MINIOS_BOOTSTRAP_TEST_ROOT=$root" "MINIOS_RUNTIME_PROBE_ROOT=$wsl2_probe_root" "MINIOS_WSL_IDENTITY_FILE=$identity_file" \
    "MINIOS_OS_RELEASE_FILE=$good_os" WSL_DISTRO_NAME=MiniOrangeOS-Dev \
    "MINIOS_ENV_ROOT=$environment_root" \
    "$script" --toolchain-only --target-user minios
grep -Fq -- "root=$environment_root" "$tool_log"
grep -Fq -- "uid=$target_uid" "$tool_log"
printf 'checkpoint=toolchain-env\n'

before_hint="$(apt_lines)"
hint_output="$(/usr/sbin/runuser -u minios -- env \
    "PATH=$PATH" "FAKE_TARGET_UID=$target_uid" "FAKE_TARGET_HOME=$root/home/minios" \
    MINIOS_BOOTSTRAP_TEST_MODE=1 "MINIOS_OS_RELEASE_FILE=$good_os" \
    "MINIOS_BOOTSTRAP_TEST_ROOT=$root" "MINIOS_RUNTIME_PROBE_ROOT=$wsl2_probe_root" "MINIOS_WSL_IDENTITY_FILE=$identity_file" \
    WSL_DISTRO_NAME=MiniOrangeOS-Dev "MINIOS_ENV_ROOT=$environment_root" \
    "$script" --target-user minios 2>&1 || true)"
[[ "$hint_output" == *'wsl.exe -d MiniOrangeOS-Dev -u root'* ]] || { printf 'hint output missing command: %s\n' "$hint_output" >&2; exit 1; }
[[ "$hint_output" == *"MINIOS_ENV_ROOT="* ]] || { printf 'hint output missing root: %s\n' "$hint_output" >&2; exit 1; }
[[ "$(apt_lines)" == "$before_hint" ]]
printf 'checkpoint=sudo-hint\n'

container_root="$root/container-root"
mkdir -p -- "$container_root"
chown "minios:$target_uid" "$container_root"
container_before="$(test -e "$wsl_conf" && sha256sum "$wsl_conf")"
"${common[@]}" MINIOS_RUNTIME_PROBE_ROOT="$container_probe_root" MINIOS_OS_RELEASE_FILE="$good_os" MINIOS_CONTAINER=1 \
    MINIOS_ENV_ROOT="$container_root" "$script" --system-only
container_after="$(test -e "$wsl_conf" && sha256sum "$wsl_conf")"
[[ "$container_before" == "$container_after" ]] || { printf 'container changed wsl.conf\n' >&2; exit 1; }
[[ -s "$container_root/state/apt-packages.lock" ]]
printf 'checkpoint=container\n'

printf 'bootstrap_fake_result=PASS\n'
'@
        $BootstrapFullPath = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'environment\bootstrap-inside.sh'))
        $BootstrapDrive = $BootstrapFullPath.Substring(0, 1).ToLowerInvariant()
        $BootstrapWslPath = "/mnt/$BootstrapDrive/" + $BootstrapFullPath.Substring(3).Replace('\', '/')
        $Harness = $Harness.Replace('__MINIOS_BOOTSTRAP_SOURCE__', $BootstrapWslPath)
        $WriterFullPath = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'environment\lib\package_state_writer.py'))
        $WriterDrive = $WriterFullPath.Substring(0, 1).ToLowerInvariant()
        $WriterWslPath = "/mnt/$WriterDrive/" + $WriterFullPath.Substring(3).Replace('\', '/')
        $Harness = $Harness.Replace('__MINIOS_PACKAGE_WRITER_SOURCE__', $WriterWslPath)
        [IO.File]::WriteAllText($HarnessPath, $Harness, [Text.UTF8Encoding]::new($false))
        $HarnessFullPath = [IO.Path]::GetFullPath($HarnessPath)
        $HarnessDrive = $HarnessFullPath.Substring(0, 1).ToLowerInvariant()
        $HarnessWslPath = "/mnt/$HarnessDrive/" + $HarnessFullPath.Substring(3).Replace('\', '/')
        $PreviousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $Output = @(& wsl.exe -d MiniOrangeOS-Dev -u root -- bash $HarnessWslPath 2>&1)
            $Status = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousErrorAction
        }
        Assert-True ($Status -eq 0) ("bootstrap fake harness 失败：" + ($Output -join "`n"))
        Assert-True (($Output -join "`n") -match 'bootstrap_fake_result=PASS') 'bootstrap fake harness 缺少 PASS'
    }
}
finally {
    Remove-Item Env:MINIOS_WSL_TEST_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:FAKE_WSL_LOG -ErrorAction SilentlyContinue
    Remove-Item Env:FAKE_WSL_LIST -ErrorAction SilentlyContinue
    Remove-Item Env:FAKE_DOWNLOAD_LOG -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $TemporaryRoot) {
        $ResolvedTemporaryRoot = [IO.Path]::GetFullPath($TemporaryRoot)
        $SystemTemporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        if (-not $ResolvedTemporaryRoot.StartsWith($SystemTemporaryRoot + '\minios-wsl-test-', [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝清理未授权测试目录：$ResolvedTemporaryRoot"
        }
        Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force
    }
}

Write-Host "result=$($Script:Passed) passed, $($Script:Failed) failed"
if ($Script:Failed -ne 0) {
    exit 1
}
