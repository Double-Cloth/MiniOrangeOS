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

if ($AuthorizedRoot -cne $ProductionAuthorizedRoot) {
    $TestPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\minios-wsl-test-'
    if ($env:MINIOS_WSL_TEST_MODE -cne '1' -or
        -not [IO.Path]::GetFullPath($AuthorizedRoot).StartsWith($TestPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $DistroName.StartsWith('MiniOrangeOS-Dev-Test-', [StringComparison]::Ordinal)) {
        throw "授权根只能是 $ProductionAuthorizedRoot；临时测试根必须位于系统临时目录"
    }
}
if ($DistroName -cne 'MiniOrangeOS-Dev' -and
    (-not $DistroName.StartsWith('MiniOrangeOS-Dev-Test-', [StringComparison]::Ordinal) -or
     $DistroName.Length -le 'MiniOrangeOS-Dev-Test-'.Length)) {
    throw "拒绝非项目 WSL 发行版名：$DistroName"
}
$Root = [IO.Path]::GetFullPath($AuthorizedRoot)
$ExpectedPath = if ($DistroName -ceq 'MiniOrangeOS-Dev') {
    [IO.Path]::GetFullPath((Join-Path $Root 'rootfs'))
} else {
    [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'drills') $DistroName))
}
if (Test-Path -LiteralPath $ExpectedPath) {
    $Item = Get-Item -LiteralPath $ExpectedPath -Force
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "路径包含 ReparsePoint：$ExpectedPath"
    }
}
$Names = @(& $WslExecutable --list --quiet)
if ($LASTEXITCODE -ne 0) { throw '无法列举 WSL 发行版' }
$Names = @($Names | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if (@($Names | Where-Object { $_ -ceq $DistroName }).Count -ne 1) {
    throw "WSL 发行版不存在（精确匹配）：$DistroName"
}
if ($Command -and $Command.Count -gt 0) {
    & $WslExecutable -d $DistroName -- @Command
}
else {
    & $WslExecutable -d $DistroName
}
if ($LASTEXITCODE -ne 0) { throw "进入 WSL 失败：$DistroName" }
