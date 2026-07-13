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
        [string]$RegisteredBasePath
    )

    function Get-ChildItem {
        param([string]$LiteralPath)
        [pscustomobject]@{ PSPath = 'HKCU:\FakeLxss\Owned' }
    }
    function Get-ItemProperty {
        param([string]$LiteralPath)
        [pscustomobject]@{
            DistributionName = $RegisteredName
            BasePath = $RegisteredBasePath
        }
    }
    function wsl.exe {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
        [IO.File]::AppendAllText($env:FAKE_WSL_LOG, (($Arguments -join ' ') + "`n"))
        if ($Arguments.Count -ge 2 -and $Arguments[0] -ceq '--list') {
            Write-Output $env:FAKE_WSL_LIST
        }
        $global:LASTEXITCODE = 0
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
$FakeLog = Join-Path $TemporaryRoot 'wsl.log'
$DownloadLog = Join-Path $TemporaryRoot 'download.log'
[IO.File]::WriteAllText(
    $FakeWsl,
    "@echo off`r`necho %*>>`"%FAKE_WSL_LOG%`"`r`nif `"%1`"==`"--list`" echo %FAKE_WSL_LIST%`r`nexit /b 0`r`n",
    [Text.Encoding]::ASCII
)
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
        Assert-True ((Read-FakeLog $FakeLog) -notmatch '--import') '已有发行版仍触发 import'
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
        & $EnterScript -DistroName $DistroName -AuthorizedRoot $AuthorizedRoot -WslExecutable $FakeWsl -Command 'true'
        Assert-True ((Read-FakeLog $FakeLog) -match "-d $([regex]::Escape($DistroName))") '精确名称未进入 fake 发行版'
    }

    Invoke-Test '真实 MiniOrangeOS-Dev 名称和 BasePath 只读验证' {
        $Names = @(& wsl.exe --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ }
        Assert-True (@($Names | Where-Object { $_ -ceq 'MiniOrangeOS-Dev' }).Count -eq 1) '真实发行版精确名称不存在'
        $LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
        $Key = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq 'MiniOrangeOS-Dev' } | Select-Object -First 1
        Assert-True ($null -ne $Key) '未找到真实发行版 Lxss 注册项'
        $BasePath = [IO.Path]::GetFullPath((Get-ItemProperty -LiteralPath $Key.PSPath).BasePath)
        $Expected = [IO.Path]::GetFullPath('D:\ApplicationData\MiniOrangeOS\rootfs')
        Assert-True ($BasePath -ceq $Expected) "真实 BasePath 不匹配：$BasePath"
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

    Invoke-Test 'bootstrap 阶段拒绝错误权限且不触发 apt 或工具链' {
        $BootstrapPath = '/mnt/d/DC/program-projects/OTHER/MiniOrangeOS/environment/bootstrap-inside.sh'
        $PreviousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $SystemOutput = @(& wsl.exe -d MiniOrangeOS-Dev -u minios -- bash $BootstrapPath --system-only 2>&1)
            $SystemStatus = $LASTEXITCODE
            Assert-True ($SystemStatus -ne 0) '普通用户执行 system-only 应失败'
            Assert-True (($SystemOutput -join "`n") -match 'root') 'system-only 失败缺少 root 诊断'

            $ToolchainOutput = @(& wsl.exe -d MiniOrangeOS-Dev -u root -- bash $BootstrapPath --toolchain-only 2>&1)
            $ToolchainStatus = $LASTEXITCODE
            Assert-True ($ToolchainStatus -ne 0) 'root 执行 toolchain-only 应失败'
            Assert-True (($ToolchainOutput -join "`n") -match '普通用户') 'toolchain-only 失败缺少普通用户诊断'
        }
        finally {
            $ErrorActionPreference = $PreviousErrorAction
        }
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
