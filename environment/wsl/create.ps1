[CmdletBinding()]
param(
    [string]$DistroName = 'MiniOrangeOS-Dev',
    [string]$AuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS',
    [string]$RootfsPath = '',
    [switch]$Bootstrap,
    [string]$WslExecutable = 'wsl.exe',
    [string]$DownloadExecutable = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProductionAuthorizedRoot = 'D:\ApplicationData\MiniOrangeOS'
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$VersionsPath = Join-Path $RepoRoot 'environment\versions.env'
$RepoWslPath = '/mnt/d/DC/program-projects/OTHER/MiniOrangeOS'

function Assert-RootOverrideAllowed {
    if ($AuthorizedRoot -cne $ProductionAuthorizedRoot) {
        $TestPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\minios-wsl-test-'
        $RequestedRoot = [IO.Path]::GetFullPath($AuthorizedRoot)
        if ($env:MINIOS_WSL_TEST_MODE -cne '1' -or
            -not $RequestedRoot.StartsWith($TestPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not $DistroName.StartsWith('MiniOrangeOS-Dev-Test-', [StringComparison]::Ordinal)) {
            throw "授权根只能是 $ProductionAuthorizedRoot；临时测试根必须位于系统临时目录"
        }
    }
}

function Assert-AllowedDistroName {
    param([string]$Name)
    if ($Name -ceq 'MiniOrangeOS-Dev') { return }
    if ($Name.StartsWith('MiniOrangeOS-Dev-Test-', [StringComparison]::Ordinal) -and
        $Name.Length -gt 'MiniOrangeOS-Dev-Test-'.Length) { return }
    throw "拒绝非项目 WSL 发行版名：$Name"
}

function Get-ExpectedInstallPath {
    param([string]$Name)
    $Root = [IO.Path]::GetFullPath($AuthorizedRoot)
    if ($Name -ceq 'MiniOrangeOS-Dev') {
        return [IO.Path]::GetFullPath((Join-Path $Root 'rootfs'))
    }
    return [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'drills') $Name))
}

function Assert-PathWithinAuthorizedRoot {
    param([string]$Path)
    $Root = [IO.Path]::GetFullPath($AuthorizedRoot).TrimEnd('\')
    $FullPath = [IO.Path]::GetFullPath($Path)
    if ($FullPath -ine $Root -and
        -not $FullPath.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) {
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
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "路径包含 ReparsePoint：$Current"
            }
        }
    }
}

function Get-WslDistributionNames {
    $Output = @(& $WslExecutable --list --quiet)
    if ($LASTEXITCODE -ne 0) { throw '无法列举 WSL 发行版' }
    return @($Output | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
}

function Test-WslDistributionExists {
    param([string]$Name)
    return @((Get-WslDistributionNames) | Where-Object { $_ -ceq $Name }).Count -eq 1
}

function Assert-WslDistributionOwnership {
    param([string]$DistroName, [string]$ExpectedPath)
    $LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    $LxssKey = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName } | Select-Object -ExpandProperty PSPath -First 1
    $RegisteredBasePath = (Get-ItemProperty -LiteralPath $LxssKey).BasePath
    if (-not $LxssKey -or -not $RegisteredBasePath) {
        throw "发行版缺少可信 Lxss BasePath：$DistroName"
    }
    $RegisteredFullPath = [IO.Path]::GetFullPath($RegisteredBasePath)
    $ExpectedFullPath = [IO.Path]::GetFullPath($ExpectedPath)
    if ($RegisteredFullPath -cne $ExpectedFullPath) {
        throw "Lxss BasePath 不匹配：registered=$RegisteredFullPath expected=$ExpectedFullPath"
    }
    [void](Assert-PathWithinAuthorizedRoot $RegisteredFullPath)
    Assert-NoReparsePointComponents $RegisteredFullPath
}

function Read-VersionLock {
    $Values = @{}
    foreach ($Line in Get-Content -LiteralPath $VersionsPath) {
        if (-not $Line -or $Line.StartsWith('#')) { continue }
        $Parts = $Line.Split('=', 2)
        if ($Parts.Count -ne 2 -or $Values.ContainsKey($Parts[0])) {
            throw "版本锁格式错误：$Line"
        }
        $Values[$Parts[0]] = $Parts[1]
    }
    foreach ($Key in @('MINIOS_WSL_IMAGE_VERSION', 'MINIOS_WSL_IMAGE_URL', 'MINIOS_WSL_IMAGE_SHA256')) {
        if (-not $Values.ContainsKey($Key) -or -not $Values[$Key]) {
            throw "版本锁缺少字段：$Key"
        }
    }
    return $Values
}

function Get-VerifiedRootfs {
    param([hashtable]$Versions)
    $Downloads = Assert-PathWithinAuthorizedRoot (Join-Path $AuthorizedRoot 'downloads')
    Assert-NoReparsePointComponents $Downloads
    [void][IO.Directory]::CreateDirectory($Downloads)
    Assert-NoReparsePointComponents $Downloads
    if ($RootfsPath) {
        $Candidate = [IO.Path]::GetFullPath($RootfsPath)
    }
    else {
        $Candidate = [IO.Path]::GetFullPath((Join-Path $Downloads ("ubuntu-{0}-wsl-amd64.wsl" -f $Versions.MINIOS_WSL_IMAGE_VERSION)))
        $Partial = $Candidate + '.partial'
        [void](Assert-PathWithinAuthorizedRoot $Partial)
        Assert-NoReparsePointComponents $Partial
        if (-not (Test-Path -LiteralPath $Candidate)) {
            if (Test-Path -LiteralPath $Partial) { Remove-Item -LiteralPath $Partial -Force }
            try {
                if ($DownloadExecutable) {
                    if ($env:MINIOS_WSL_TEST_MODE -cne '1') { throw '仅测试模式允许替换下载后端' }
                    & $DownloadExecutable $Versions.MINIOS_WSL_IMAGE_URL $Partial
                    if ($LASTEXITCODE -ne 0) { throw 'WSL rootfs 下载失败' }
                }
                else {
                    Invoke-WebRequest -UseBasicParsing -Uri $Versions.MINIOS_WSL_IMAGE_URL -OutFile $Partial
                }
                $PartialHash = (Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($PartialHash -cne $Versions.MINIOS_WSL_IMAGE_SHA256) {
                    throw "WSL rootfs SHA-256 不匹配：$PartialHash"
                }
                Move-Item -LiteralPath $Partial -Destination $Candidate
            }
            catch {
                if (Test-Path -LiteralPath $Partial) { Remove-Item -LiteralPath $Partial -Force }
                throw
            }
        }
    }
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        throw "WSL rootfs 不存在：$Candidate"
    }
    Assert-NoReparsePointComponents $Candidate
    $ActualHash = (Get-FileHash -LiteralPath $Candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -cne $Versions.MINIOS_WSL_IMAGE_SHA256) {
        throw "WSL rootfs SHA-256 不匹配：$ActualHash"
    }
    return $Candidate
}

function Invoke-Bootstrap {
    & $WslExecutable -d $DistroName -u root -- bash "$RepoWslPath/environment/bootstrap-inside.sh" --system-only --target-user minios
    if ($LASTEXITCODE -ne 0) { throw 'WSL system bootstrap 失败' }
    & $WslExecutable -d $DistroName -u minios -- bash "$RepoWslPath/environment/bootstrap-inside.sh" --toolchain-only --target-user minios
    if ($LASTEXITCODE -ne 0) { throw 'WSL toolchain bootstrap 失败' }
}

Assert-RootOverrideAllowed
Assert-AllowedDistroName $DistroName
$ExpectedPath = Get-ExpectedInstallPath $DistroName
[void](Assert-PathWithinAuthorizedRoot $ExpectedPath)
Assert-NoReparsePointComponents ([IO.Path]::GetFullPath($AuthorizedRoot))
Assert-NoReparsePointComponents $ExpectedPath

if (Test-WslDistributionExists $DistroName) {
    Assert-WslDistributionOwnership $DistroName $ExpectedPath
    Write-Host "发行版已存在且 ownership 验证通过：$DistroName"
    if ($Bootstrap) { Invoke-Bootstrap }
    return
}

$Versions = Read-VersionLock
$VerifiedRootfs = Get-VerifiedRootfs $Versions
[void][IO.Directory]::CreateDirectory($ExpectedPath)
Assert-NoReparsePointComponents $ExpectedPath
& $WslExecutable --import $DistroName $ExpectedPath $VerifiedRootfs --version 2
if ($LASTEXITCODE -ne 0) { throw "WSL import 失败：$DistroName" }
Assert-WslDistributionOwnership $DistroName $ExpectedPath
Write-Host "发行版创建完成：$DistroName"
if ($Bootstrap) { Invoke-Bootstrap }
