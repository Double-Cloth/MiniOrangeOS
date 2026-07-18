[CmdletBinding()]
param(
    [string]$DistroName = 'MiniOrangeOS-Dev',
    [string]$AuthorizedRoot = '',
    [string]$WslExecutable = 'wsl.exe',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$CommonPath = [IO.Path]::Combine($PSScriptRoot, 'common.ps1')
. ([scriptblock]::Create([IO.File]::ReadAllText($CommonPath)))
$PathConfiguration = Get-MiniosWslPathConfiguration -WslDirectory $PSScriptRoot
$ProductionAuthorizedRoot = $PathConfiguration.AuthorizedRoot
if (-not $AuthorizedRoot) { $AuthorizedRoot = $ProductionAuthorizedRoot }
$RepoWslPath = ConvertTo-MiniosWslPath $PathConfiguration.RepoRoot
$SafeTestDistroPattern = '^MiniOrangeOS-Dev-Test-[A-Za-z0-9][A-Za-z0-9_-]*$'
$script:LastWslShellExitCode = 0
$WorkspaceRunner = @'
set -euo pipefail

readonly source_path="$1"
readonly shell_command="$2"
case "$source_path" in
    /mnt/[a-z]/*) ;;
    *)
        printf 'MiniOrangeOS workspace source is not a WSL local-drive path: %s\n' "$source_path" >&2
        exit 2
        ;;
esac
if [[ ! -d "$source_path" || -L "$source_path" ]]; then
    printf 'MiniOrangeOS workspace source is not a regular directory: %s\n' "$source_path" >&2
    exit 2
fi

readonly workspace='/run/miniorangeos-workspace'
if [[ -L "$workspace" || ( -e "$workspace" && ! -d "$workspace" ) ]]; then
    printf 'MiniOrangeOS workspace mountpoint is not a regular directory: %s\n' "$workspace" >&2
    exit 2
fi
if mountpoint -q -- "$workspace"; then
    printf 'MiniOrangeOS workspace mountpoint is unexpectedly mounted: %s\n' "$workspace" >&2
    exit 2
fi
install -d -o root -g root -m 0755 -- "$workspace"
if [[ "$(stat -c '%F|%u|%g|%a' -- "$workspace")" != 'directory|0|0|755' ]]; then
    printf 'MiniOrangeOS workspace mountpoint metadata is invalid: %s\n' "$workspace" >&2
    exit 2
fi
mounted=0
cleanup() {
    local status=$?
    trap - EXIT
    if ((mounted)); then
        if ! umount -- "$workspace"; then
            printf 'MiniOrangeOS workspace unmount failed: %s\n' "$workspace" >&2
            status=1
        fi
    fi
    exit "$status"
}
trap cleanup EXIT

mount --bind "$source_path" "$workspace"
mounted=1
runuser -u minios -- env MINIOS_REPO_SOURCE="$source_path" MINIOS_REPO_MOUNT="$workspace" \
    bash -c 'cd -- "$1" && exec bash -lc "$2"' bash "$workspace" "$shell_command"
'@

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
        $Current = [IO.Path]::Combine($Current, $Part)
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
    $Registration = Get-ItemProperty -LiteralPath $LxssKey
    $RegisteredBasePath = $Registration.BasePath
    $RegisteredVersion = $Registration.Version
    if ($LxssMatches[0].PSPath -cne $LxssKey) { throw "Lxss 注册项在 ownership 检查期间发生变化：$DistroName" }
    if (-not $LxssKey -or -not $RegisteredBasePath) { throw "发行版缺少可信 Lxss BasePath：$DistroName" }
    if ($RegisteredVersion -ne 2) { throw "发行版必须是 WSL2：$DistroName Version=$RegisteredVersion" }
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

function ConvertTo-WindowsNativeArgument {
    param([AllowEmptyString()][string]$Value)
    # Windows PowerShell 5.1 会重新序列化 native argv；按 CommandLineToArgvW
    # 规则包裹单个 shell 字符串，避免其中的引号改变参数边界。
    $Escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $Escaped = [regex]::Replace($Escaped, '(\\+)$', '$1$1')
    return '"' + $Escaped + '"'
}

function Invoke-WslWorkspaceCommand {
    param(
        [string]$Executable,
        [string]$Name,
        [string]$SourcePath,
        [AllowEmptyString()][string]$ShellCommand
    )
    if ([IO.Path]::GetExtension($Executable) -ieq '.cmd') {
        # 测试替身；生产 wsl.exe 与精确 argv 测试均走 ProcessStartInfo。
        & $Executable -d $Name -u root --exec unshare --mount --propagation private `
            bash -c $WorkspaceRunner bash $SourcePath $ShellCommand
        $script:LastWslShellExitCode = $LASTEXITCODE
        return
    }
    $ResolvedExecutable = @(Get-Command -Name $Executable -CommandType Application -ErrorAction Stop)[0].Source
    $Info = [Diagnostics.ProcessStartInfo]::new()
    $Info.FileName = $ResolvedExecutable
    $Info.UseShellExecute = $false
    # wsl.exe 的 option parser 不接受被引号包裹的固定选项；发行版名已经过
    # 单段白名单校验。Runner、源路径和用户命令分别按 CommandLineToArgvW
    # 编码，源路径中的 Shell/Make 特殊字符始终只作为 argv 数据传递。
    $Info.Arguments = '-d ' + $Name +
        ' -u root --exec unshare --mount --propagation private bash -c ' +
        (ConvertTo-WindowsNativeArgument $WorkspaceRunner) + ' bash ' +
        (ConvertTo-WindowsNativeArgument $SourcePath) + ' ' +
        (ConvertTo-WindowsNativeArgument $ShellCommand)
    $Process = [Diagnostics.Process]::Start($Info)
    $Process.WaitForExit()
    $script:LastWslShellExitCode = $Process.ExitCode
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
if ($null -ne $Command -and $Command.Count -gt 1) {
    throw '-Command 只接受单个完整 shell 命令字符串'
}
$Root = [IO.Path]::GetFullPath($AuthorizedRoot)
$ExpectedPath = if ($DistroName -ceq 'MiniOrangeOS-Dev') {
    [IO.Path]::GetFullPath([IO.Path]::Combine($Root, 'rootfs'))
} else {
    [IO.Path]::GetFullPath([IO.Path]::Combine($Root, 'drills', $DistroName))
}
Assert-NoReparsePointComponents $ExpectedPath
$Names = @(& $WslExecutable --list --quiet)
if ($LASTEXITCODE -ne 0) { throw '无法列举 WSL 发行版' }
$Names = @($Names | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if (@($Names | Where-Object { $_ -ceq $DistroName }).Count -ne 1) { throw "WSL 发行版不存在（精确匹配）：$DistroName" }
Assert-WslDistributionOwnership $DistroName $ExpectedPath
if ($null -ne $Command -and $Command.Count -eq 1) {
    Invoke-WslWorkspaceCommand $WslExecutable $DistroName $RepoWslPath $Command[0]
}
else {
    Invoke-WslWorkspaceCommand $WslExecutable $DistroName $RepoWslPath 'exec bash -l'
}
$global:LASTEXITCODE = $script:LastWslShellExitCode
if ($LASTEXITCODE -ne 0) { throw "进入 WSL 失败：$DistroName" }
