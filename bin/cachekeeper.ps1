# `cachekeeper audit` / `cachekeeper events` in PowerShell, as bin/cachekeeper does for sh. Claude Code puts a
# plugin's bin/ directory on the Bash tool's PATH only, so on Windows without Git Bash the audit skill runs this file
# by its path. Python writes to this window or pipe itself: its UTF-8 (the Korean report) is never re-encoded.
$root = [IO.Path]::GetDirectoryName($PSScriptRoot)

function Invoke-Python([string]$Path, [string]$Arguments, [switch]$Quiet) {
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Path
        $info.Arguments = $Arguments
        $info.UseShellExecute = $false
        $info.CreateNoWindow = [Console]::IsOutputRedirected
        $info.RedirectStandardOutput = [bool]$Quiet
        $info.RedirectStandardError = $true
        $info.EnvironmentVariables['PYTHONPATH'] = if ($env:PYTHONPATH) { "$root$([IO.Path]::PathSeparator)$env:PYTHONPATH" } else { $root }
        $process = [System.Diagnostics.Process]::Start($info)
        $errors = if ($Quiet) { [IO.Stream]::Null } else { [Console]::OpenStandardError() }
        $copy = $process.StandardError.BaseStream.CopyToAsync($errors)
        if ($Quiet) { $process.StandardOutput.BaseStream.CopyTo([IO.Stream]::Null) }
        $process.WaitForExit()
        $copy.Wait()
        return $process.ExitCode
    } catch {
        return -1
    }
}

# One argument of a Windows command line: quoted when it has a space or a quote, backslashes doubled where the
# quoting needs it.
function ConvertTo-Argument([string]$Value) {
    if ($Value -and $Value -notmatch '[\s"]') { return $Value }
    return '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

$python = $null
foreach ($candidate in 'python3', 'python', 'py -3') {
    $name, $options = $candidate -split ' ', 2
    $command = @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)[0]
    if ($command -and (Invoke-Python $command.Path "$options -c `"import sys; sys.exit(sys.version_info < (3, 8))`"" -Quiet) -eq 0) {
        $python = $command.Path
        break
    }
}
if (-not $python) {
    [Console]::Error.WriteLine('cachekeeper: Python 3.8 or newer is required')
    exit 1
}
$arguments = @("$options -m cachekeeper.cli") + @($args | ForEach-Object { ConvertTo-Argument "$_" })
exit (Invoke-Python $python ($arguments -join ' '))
