[CmdletBinding()]
param(
    [string]$DistroName = 'MiniOrangeOS-Dev',
    [string]$AuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS',
    [string]$WslExecutable = 'wsl.exe',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProductionAuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS'
$SafeTestDistroPattern = '^MiniOrangeOS-Dev-Test-[A-Za-z0-9][A-Za-z0-9_-]*$'

function Assert-AllowedDistroName {
    if ($DistroName -ceq 'MiniOrangeOS-Dev') { return }
    if ($DistroName -cmatch '^MiniOrangeOS-Dev-Test-[A-Za-z0-9][A-Za-z0-9_-]*$') { return }
    throw "拒绝非项目 WSL 发行版名：$DistroName"
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
    $LxssMatches = @(Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName })
    if ($LxssMatches.Count -ne 1) { throw "Lxss 注册项必须唯一：$DistroName count=$($LxssMatches.Count)" }
    $LxssKey = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName } | Select-Object -ExpandProperty PSPath -First 1
    $RegisteredBasePath = (Get-ItemProperty -LiteralPath $LxssKey).BasePath
    if ($LxssMatches[0].PSPath -cne $LxssKey) { throw "Lxss 注册项在 ownership 检查期间发生变化：$DistroName" }
    if (-not $LxssKey -or -not $RegisteredBasePath) { throw "发行版缺少可信 Lxss BasePath：$DistroName" }
    $RegisteredFullPath = [IO.Path]::GetFullPath($RegisteredBasePath)
    $ExpectedFullPath = [IO.Path]::GetFullPath($ExpectedPath)
    if ($RegisteredFullPath -cne $ExpectedFullPath) { throw "Lxss BasePath 不匹配：$RegisteredFullPath" }
    Assert-NoReparsePointComponents $RegisteredFullPath
    if (-not (Test-Path -LiteralPath $RegisteredFullPath -PathType Container)) { throw "注册 BasePath 末端必须是现有目录：$RegisteredFullPath" }
    $RegisteredItem = Get-Item -LiteralPath $RegisteredFullPath -Force
    if (-not $RegisteredItem.PSIsContainer -or ($RegisteredItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "注册 BasePath 末端不是可信普通目录：$RegisteredFullPath"
    }
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
$Root = [IO.Path]::GetFullPath($AuthorizedRoot)
$ExpectedPath = if ($DistroName -ceq 'MiniOrangeOS-Dev') {
    [IO.Path]::GetFullPath((Join-Path $Root 'rootfs'))
} else {
    [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'drills') $DistroName))
}
Assert-NoReparsePointComponents $ExpectedPath
$Names = @(& $WslExecutable --list --quiet)
if ($LASTEXITCODE -ne 0) { throw '无法列举 WSL 发行版' }
$Names = @($Names | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if (@($Names | Where-Object { $_ -ceq $DistroName }).Count -ne 1) { throw "WSL 发行版不存在（精确匹配）：$DistroName" }
Assert-WslDistributionOwnership $DistroName $ExpectedPath
if ($Command -and $Command.Count -gt 0) {
    & $WslExecutable -d $DistroName -- @Command
}
else {
    & $WslExecutable -d $DistroName
}
if ($LASTEXITCODE -ne 0) { throw "进入 WSL 失败：$DistroName" }
