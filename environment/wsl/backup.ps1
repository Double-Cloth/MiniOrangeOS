[CmdletBinding()]
param(
    [string]$DistroName = 'MiniOrangeOS-Dev',
    [string]$AuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS',
    [string]$ExportPath = '',
    [string]$WslExecutable = 'wsl.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProductionAuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS'

function Assert-AllowedDistroName {
    if ($DistroName -ceq 'MiniOrangeOS-Dev') { return }
    if ($DistroName.StartsWith('MiniOrangeOS-Dev-Test-', [StringComparison]::Ordinal) -and
        $DistroName.Length -gt 'MiniOrangeOS-Dev-Test-'.Length) { return }
    throw "拒绝非项目 WSL 发行版名：$DistroName"
}

function Get-ExpectedInstallPath {
    $Root = [IO.Path]::GetFullPath($AuthorizedRoot)
    if ($DistroName -ceq 'MiniOrangeOS-Dev') { return [IO.Path]::GetFullPath((Join-Path $Root 'rootfs')) }
    return [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'drills') $DistroName))
}

function Assert-PathWithinRoot {
    param([string]$Path, [string]$RootPath)
    $RootFullPath = [IO.Path]::GetFullPath($RootPath).TrimEnd('\')
    $FullPath = [IO.Path]::GetFullPath($Path)
    if ($FullPath -ine $RootFullPath -and
        -not $FullPath.StartsWith($RootFullPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "路径越过授权根：$FullPath"
    }
    return $FullPath
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

function Get-WslDistributionNames {
    $Output = @(& $WslExecutable --list --quiet)
    if ($LASTEXITCODE -ne 0) { throw '无法列举 WSL 发行版' }
    return @($Output | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
}

function Assert-WslDistributionOwnership {
    param([string]$DistroName, [string]$ExpectedPath)
    $LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    $LxssKey = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName } | Select-Object -ExpandProperty PSPath -First 1
    $RegisteredBasePath = (Get-ItemProperty -LiteralPath $LxssKey).BasePath
    if (-not $LxssKey -or -not $RegisteredBasePath) { throw "发行版缺少可信 Lxss BasePath：$DistroName" }
    $RegisteredFullPath = [IO.Path]::GetFullPath($RegisteredBasePath)
    $ExpectedFullPath = [IO.Path]::GetFullPath($ExpectedPath)
    if ($RegisteredFullPath -cne $ExpectedFullPath) { throw "Lxss BasePath 不匹配：$RegisteredFullPath" }
    [void](Assert-PathWithinRoot $RegisteredFullPath $AuthorizedRoot)
    Assert-NoReparsePointComponents $RegisteredFullPath
}

if ($AuthorizedRoot -cne $ProductionAuthorizedRoot) {
    $TestPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\minios-wsl-test-'
    if ($env:MINIOS_WSL_TEST_MODE -cne '1' -or
        -not [IO.Path]::GetFullPath($AuthorizedRoot).StartsWith($TestPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $DistroName.StartsWith('MiniOrangeOS-Dev-Test-', [StringComparison]::Ordinal)) {
        throw "授权根只能是 $ProductionAuthorizedRoot；临时测试根必须位于系统临时目录"
    }
}
Assert-AllowedDistroName
$ExpectedPath = Get-ExpectedInstallPath
[void](Assert-PathWithinRoot $ExpectedPath $AuthorizedRoot)
Assert-NoReparsePointComponents ([IO.Path]::GetFullPath($AuthorizedRoot))
Assert-NoReparsePointComponents $ExpectedPath
$ExportsRoot = Assert-PathWithinRoot (Join-Path $AuthorizedRoot 'exports') $AuthorizedRoot
if (-not $ExportPath) {
    $ExportPath = Join-Path $ExportsRoot ("{0}-{1}.tar" -f $DistroName, (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$ExportPath = Assert-PathWithinRoot $ExportPath $ExportsRoot
$PartialPath = $ExportPath + '.partial'
[void](Assert-PathWithinRoot $PartialPath $ExportsRoot)
Assert-NoReparsePointComponents $ExportPath
if (Test-Path -LiteralPath $ExportPath) { throw "拒绝覆盖已有备份：$ExportPath" }
if (Test-Path -LiteralPath $PartialPath) { throw "拒绝覆盖未知临时备份：$PartialPath" }
$Names = Get-WslDistributionNames
if (@($Names | Where-Object { $_ -ceq $DistroName }).Count -ne 1) { throw "WSL 发行版不存在：$DistroName" }
Assert-WslDistributionOwnership $DistroName $ExpectedPath
[void][IO.Directory]::CreateDirectory($ExportsRoot)
Assert-NoReparsePointComponents $ExportsRoot
& $WslExecutable --terminate $DistroName
if ($LASTEXITCODE -ne 0) { throw "终止 WSL 失败：$DistroName" }
& $WslExecutable --export $DistroName $PartialPath
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath $PartialPath) { Remove-Item -LiteralPath $PartialPath -Force }
    throw "导出 WSL 失败：$DistroName"
}
Move-Item -LiteralPath $PartialPath -Destination $ExportPath
Write-Host "备份完成：$ExportPath"
