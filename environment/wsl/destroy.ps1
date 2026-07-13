[CmdletBinding()]
param(
    [string]$DistroName = 'MiniOrangeOS-Dev',
    [string]$AuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS',
    [switch]$Apply,
    [string]$ConfirmName = '',
    [string]$WslExecutable = 'wsl.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProductionAuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS'
$SafeTestDistroPattern = '^MiniOrangeOS-Dev-Test-[A-Za-z0-9][A-Za-z0-9_-]*$'
$Script:DestructionConfirmed = $false

function Assert-AllowedDistroName {
    if ($DistroName -ceq 'MiniOrangeOS-Dev') { return }
    if ($DistroName -cmatch '^MiniOrangeOS-Dev-Test-[A-Za-z0-9][A-Za-z0-9_-]*$') { return }
    throw "拒绝非项目 WSL 发行版名：$DistroName"
}

function Get-ExpectedInstallPath {
    $Root = [IO.Path]::GetFullPath($AuthorizedRoot)
    if ($DistroName -ceq 'MiniOrangeOS-Dev') { return [IO.Path]::GetFullPath((Join-Path $Root 'rootfs')) }
    return [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'drills') $DistroName))
}

function Assert-NoReparsePointComponents {
    param([string]$Path)
    $FullPath = [IO.Path]::GetFullPath($Path)
    $Current = [IO.Path]::GetPathRoot($FullPath)
    foreach ($Part in $FullPath.Substring($Current.Length).Split('\')) {
        if (-not $Part) { continue }
        $Current = Join-Path $Current $Part
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "路径包含 ReparsePoint：$Current" }
        }
    }
}

function Assert-WslDistributionOwnership {
    param([string]$DistroName, [string]$ExpectedPath)
    $LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    $LxssKey = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName } | Select-Object -ExpandProperty PSPath -First 1
    $Registration = Get-ItemProperty -LiteralPath $LxssKey
    $RegisteredBasePath = $Registration.BasePath
    $RegisteredVersion = $Registration.Version
    $LxssMatches = @(Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName })
    if ($LxssMatches.Count -ne 1) { throw "Lxss 注册项必须唯一：$DistroName count=$($LxssMatches.Count)" }
    if ($LxssMatches[0].PSPath -cne $LxssKey) { throw "Lxss 注册项在 ownership 检查期间发生变化：$DistroName" }
    if (-not $LxssKey -or -not $RegisteredBasePath) { throw "发行版缺少可信 Lxss BasePath：$DistroName" }
    if ($RegisteredVersion -ne 2) { throw "发行版必须是 WSL2：$DistroName Version=$RegisteredVersion" }
    $RegisteredFullPath = [IO.Path]::GetFullPath($RegisteredBasePath)
    $ExpectedFullPath = [IO.Path]::GetFullPath($ExpectedPath)
    if ($RegisteredFullPath -cne $ExpectedFullPath) { throw "Lxss BasePath 不匹配：registered=$RegisteredFullPath expected=$ExpectedFullPath" }
    $RootFullPath = [IO.Path]::GetFullPath($AuthorizedRoot).TrimEnd('\')
    if ($RegisteredFullPath -ine $RootFullPath -and
        -not $RegisteredFullPath.StartsWith($RootFullPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "注册路径越过授权根：$RegisteredFullPath"
    }
    $RegisteredItem = Get-Item -LiteralPath $RegisteredFullPath -Force
    if ($RegisteredItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "注册路径本身是 ReparsePoint：$RegisteredFullPath"
    }
    if (-not $RegisteredItem.PSIsContainer -or -not (Test-Path -LiteralPath $RegisteredFullPath -PathType Container)) {
        throw "注册 BasePath 末端必须是现有普通目录：$RegisteredFullPath"
    }
    Assert-NoReparsePointComponents $RegisteredFullPath
}

function Confirm-WslDestruction {
    param([switch]$Apply, [string]$ConfirmName, [string]$DistroName)
    if (-not $Apply) {
        if ($ConfirmName) { throw '已提供确认名称，但缺少 -Apply' }
        Write-Host "预览：将定向注销 $DistroName；使用 -Apply -ConfirmName $DistroName 执行。"
        $Script:DestructionConfirmed = $false
        return
    }
    if ($ConfirmName -cne $DistroName) {
        throw "确认名称必须区分大小写并精确等于：$DistroName"
    }
    $Script:DestructionConfirmed = $true
}

function Invoke-ExactWslUnregister {
    param([string]$DistroName, [string]$WslExecutable)
    if ($WslExecutable -cne 'wsl.exe') { throw '危险 helper 禁止替换 WSL 可执行文件' }
    wsl.exe --terminate $DistroName
    if ($LASTEXITCODE -ne 0) { throw "终止 WSL 失败：$DistroName" }
    wsl.exe --unregister $DistroName
    if ($LASTEXITCODE -ne 0) { throw "注销 WSL 失败：$DistroName" }
}

if ($AuthorizedRoot -cne $ProductionAuthorizedRoot) {
    $TestPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\minios-wsl-test-'
    if ($env:MINIOS_WSL_TEST_MODE -cne '1' -or
        -not [IO.Path]::GetFullPath($AuthorizedRoot).StartsWith($TestPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not ($DistroName -cmatch $SafeTestDistroPattern)) {
        throw "授权根只能是 $ProductionAuthorizedRoot；临时测试根必须位于系统临时目录"
    }
}
Assert-AllowedDistroName
$ExpectedPath = Get-ExpectedInstallPath
Assert-NoReparsePointComponents ([IO.Path]::GetFullPath($AuthorizedRoot))
Assert-NoReparsePointComponents $ExpectedPath
$Names = @(& $WslExecutable --list --quiet)
if ($LASTEXITCODE -ne 0) { throw '无法列举 WSL 发行版' }
$Names = @($Names | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if (@($Names | Where-Object { $_ -ceq $DistroName }).Count -ne 1) { throw "WSL 发行版不存在：$DistroName" }

Assert-WslDistributionOwnership $DistroName $ExpectedPath
Confirm-WslDestruction -Apply:$Apply -ConfirmName $ConfirmName -DistroName $DistroName
if (-not $Script:DestructionConfirmed) { return }
Invoke-ExactWslUnregister -DistroName $DistroName -WslExecutable $WslExecutable
Assert-NoReparsePointComponents $ExpectedPath
if (Test-Path -LiteralPath $ExpectedPath) {
    $Remaining = @(Get-ChildItem -LiteralPath $ExpectedPath -Force)
    if ($Remaining.Count -eq 0) { Remove-Item -LiteralPath $ExpectedPath -Force }
}
Write-Host "定向注销完成：$DistroName"
