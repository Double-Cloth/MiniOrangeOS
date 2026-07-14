function Get-MiniosWslPathConfiguration {
    param([Parameter(Mandatory = $true)][string]$WslDirectory)

    $RepoRoot = [IO.Path]::GetFullPath((Join-Path $WslDirectory '..\..'))
    $ConfigPath = Join-Path $RepoRoot 'config\wsl.psd1'
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "Missing WSL path configuration: $ConfigPath"
    }

    $Configuration = Import-PowerShellDataFile -LiteralPath $ConfigPath
    $AuthorizedRoot = [string]$Configuration.AuthorizedRoot
    if (-not $AuthorizedRoot -or -not [IO.Path]::IsPathRooted($AuthorizedRoot)) {
        throw "config/wsl.psd1 AuthorizedRoot must be an absolute path"
    }
    $CanonicalAuthorizedRoot = [IO.Path]::GetFullPath($AuthorizedRoot)
    $VolumeRoot = [IO.Path]::GetPathRoot($CanonicalAuthorizedRoot)
    if ($CanonicalAuthorizedRoot -cne $AuthorizedRoot -or
        $CanonicalAuthorizedRoot.TrimEnd('\') -ceq $VolumeRoot.TrimEnd('\')) {
        throw "config/wsl.psd1 AuthorizedRoot must be canonical and cannot be a volume root"
    }

    return [pscustomobject]@{
        RepoRoot = $RepoRoot
        AuthorizedRoot = $CanonicalAuthorizedRoot
    }
}

function ConvertTo-MiniosWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $FullPath = [IO.Path]::GetFullPath($WindowsPath)
    $PathRoot = [IO.Path]::GetPathRoot($FullPath)
    if ($PathRoot -cnotmatch '^([A-Za-z]):\\$') {
        throw "The repository must be on a local drive accessible through WSL /mnt/<drive>: $FullPath"
    }
    $Drive = $Matches[1].ToLowerInvariant()
    $RelativePath = $FullPath.Substring($PathRoot.Length).Replace('\', '/')
    return "/mnt/$Drive/$RelativePath"
}

function ConvertTo-MiniosShellLiteral {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)

    return "'" + $Value.Replace("'", "'`"'`"'") + "'"
}
