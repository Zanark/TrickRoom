param(
    [string]$Source = '',
    [ValidateSet('none', 'left', 'right', '180')][string]$Rotate = 'none',
    [switch]$Demo,
    [switch]$NoMirror,
    [string]$Avatar = '',
    [string]$AvatarProfile = '',
    [string]$AvatarMode = 'live',
    [switch]$NoRigMotion,
    [ValidateSet('world', 'image')][string]$RigSpace = 'world',
    [switch]$NoRigConstraints,
    [switch]$RelaxMissing,
    [switch]$FaceResponse,
    [switch]$Headless,
    [string]$RenderVideo = '',
    [string]$Report = '',
    [string]$Snapshot = '',
    [double]$Seconds = 10,
    [double]$StartSeconds = 0,
    [string]$RenderSize = '960x720',
    [switch]$CleanOutput
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Run .\Setup-TrickRoom.ps1 first. Python 3.12 is required.'
}
$Arguments = @('-m', 'trickroom', '--rotate', $Rotate, '--rig-space', $RigSpace)
if ($Source) { $Arguments += @('--source', $Source) }
if ($Demo) { $Arguments += '--demo' }
if ($NoMirror) { $Arguments += '--no-mirror' }
if ($Avatar) { $Arguments += @('--avatar', $Avatar, '--avatar-mode', $AvatarMode) }
if ($AvatarProfile) { $Arguments += @('--avatar-profile', $AvatarProfile) }
if ($NoRigMotion) { $Arguments += '--no-rig-motion' }
if ($NoRigConstraints) { $Arguments += '--no-rig-constraints' }
if ($RelaxMissing) { $Arguments += '--relax-missing' }
if ($FaceResponse) { $Arguments += '--face-response' }
if ($Headless) { $Arguments += '--headless' }
if ($RenderVideo) { $Arguments += @('--render-video', $RenderVideo) }
if ($Report) { $Arguments += @('--report', $Report) }
if ($Snapshot) { $Arguments += @('--snapshot', $Snapshot) }
if ($PSBoundParameters.ContainsKey('Seconds')) {
    $Arguments += @('--seconds', $Seconds.ToString([Globalization.CultureInfo]::InvariantCulture))
}
if ($PSBoundParameters.ContainsKey('StartSeconds')) {
    $Arguments += @('--start-seconds', $StartSeconds.ToString([Globalization.CultureInfo]::InvariantCulture))
}
if ($PSBoundParameters.ContainsKey('RenderSize')) { $Arguments += @('--render-size', $RenderSize) }
if ($CleanOutput) { $Arguments += '--clean-output' }
Push-Location $PSScriptRoot
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "TrickRoom exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
