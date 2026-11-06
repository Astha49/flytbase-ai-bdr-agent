# Start AETHER v7 with an in-app protected new-enquiry workflow. Original data stays in its own project.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$parent = Split-Path -Parent $here
$paths = @(
    (Join-Path $parent 'Flytbase-inbound-agent'),
    (Join-Path $env:USERPROFILE 'Downloads\Flytbase-inbound-agent'),
    'F:\Downloads\Flytbase-inbound-agent',
    (Join-Path (Split-Path -Parent $parent) 'Flytbase-inbound-agent')
)
$original = $null
foreach ($candidate in $paths) {
    if ((Test-Path (Join-Path $candidate 'runs')) -and (Test-Path (Join-Path $candidate 'app.py'))) {
        $original = $candidate
        break
    }
}
$python = 'python'
if ($original) {
    $embeddedPython = Join-Path $original '.venv\Scripts\python.exe'
    if (Test-Path $embeddedPython) { $python = $embeddedPython }
    $env:AETHER_RUNS_DIR = Join-Path $original 'runs'
    $env:AETHER_SOURCE_ROOT = $original
    Write-Host "AETHER found original saved analyses: $env:AETHER_RUNS_DIR" -ForegroundColor Cyan
} else {
    Write-Host 'Source project not detected; use the sidebar to load the runs folder.' -ForegroundColor Yellow
}
Set-Location $here
& $python -m streamlit run aether_app.py --server.port 8506
