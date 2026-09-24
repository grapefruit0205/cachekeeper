# Run a cachekeeper hook with a Python 3.8+ this machine has, as hooks/run does for sh. On Windows without Git Bash,
# Claude Code runs a plugin's hook commands in PowerShell, and each command in hooks.json then runs this file.
#
# Python reads the event from the hook's stdin and writes its answer to the hook's stdout itself, and its stderr is
# copied byte for byte: through PowerShell's own pipeline the text would be decoded in the console code page (cp949,
# cp1252), and Windows PowerShell 5.1 would turn the keep-alive's message into error records. Without a Python, stay
# silent and exit 0: a PreModelSwitch hook that fails or times out would block the switch.
param([string]$HookEvent)

$root = [IO.Path]::GetDirectoryName($PSScriptRoot)

function Invoke-Python([string]$Path, [string]$Arguments, [switch]$Quiet) {
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Path
        $info.Arguments = $Arguments
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
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
    [Console]::OpenStandardInput().CopyTo([IO.Stream]::Null)
    exit 0
}
exit (Invoke-Python $python "$options -m cachekeeper.hook $HookEvent")
