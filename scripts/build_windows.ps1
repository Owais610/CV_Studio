param(
    [string]$Python = 'python',
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
$studioRoot = Split-Path -Parent $PSScriptRoot
$studioBuildPython = Join-Path $studioRoot '.build-venv\Scripts\python.exe'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Build the Windows application on Windows.'
}
Push-Location $studioRoot
try {
    if (-not (Test-Path -LiteralPath $studioBuildPython)) {
        & $Python -m venv (Join-Path $studioRoot '.build-venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the build environment.' }
    }
    if (-not $SkipInstall) {
        & $studioBuildPython -m pip install -r (Join-Path $studioRoot 'requirements-build.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies.' }
    }
    & $studioBuildPython -m PyInstaller --noconfirm `
        --distpath (Join-Path $studioRoot 'dist') `
        --workpath (Join-Path $studioRoot 'build') `
        (Join-Path $studioRoot 'packaging\CV_Studio.spec')
    if ($LASTEXITCODE -ne 0) { throw 'Windows executable build failed.' }
    $studioExe = Join-Path $studioRoot 'dist\CV Studio.exe'
    $studioSmokeDirectory = Join-Path $studioRoot 'build\standalone-check'
    New-Item -ItemType Directory -Path $studioSmokeDirectory -Force | Out-Null
    $studioReport = Join-Path $studioSmokeDirectory 'report.json'
    if (Test-Path -LiteralPath $studioReport) {
        Remove-Item -LiteralPath $studioReport
    }
    $studioPreviousEnvironment = @{
        Path = $env:PATH; PythonPath = $env:PYTHONPATH; PythonHome = $env:PYTHONHOME
    }
    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:PYTHONPATH = $null
        $env:PYTHONHOME = $null
        $studioProcess = Start-Process -FilePath $studioExe `
            -ArgumentList @('--smoke-test', ('"{0}"' -f $studioReport)) `
            -WorkingDirectory $studioSmokeDirectory -WindowStyle Hidden -PassThru
        if (-not $studioProcess.WaitForExit(60000)) {
            $studioProcess.Kill()
            throw 'Standalone application check timed out.'
        }
    } finally {
        $env:PATH = $studioPreviousEnvironment.Path
        $env:PYTHONPATH = $studioPreviousEnvironment.PythonPath
        $env:PYTHONHOME = $studioPreviousEnvironment.PythonHome
    }
    if ($studioProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $studioReport)) {
        throw "Standalone application check failed. See $studioReport"
    }
    $studioResults = Get-Content -LiteralPath $studioReport -Raw | ConvertFrom-Json
    if (-not $studioResults.ok -or -not $studioResults.frozen) {
        throw "Standalone application check failed. See $studioReport"
    }
    $studioReadme = Join-Path $studioRoot 'dist\README-Windows.txt'
    @'
CV Studio for Windows (64-bit)

Double-click CV Studio.exe. Python is not required.
Save your editable CV as JSON, then use Export PDF for the finished document.
The executable can be moved to another folder; your documents are saved where
you choose. Keep your JSON files when updating the application.

Source and build instructions: https://github.com/Owais610/CV_Studio
License information: CV Studio-LICENSES.txt
'@ | Set-Content -LiteralPath $studioReadme -Encoding UTF8
    $studioLicense = Join-Path $studioRoot 'dist\CV Studio-LICENSES.txt'
    $studioLicenseInputs = @(
        (Join-Path $studioRoot 'packaging\THIRD_PARTY_NOTICES.txt'),
        (Join-Path $studioRoot 'LICENSE'),
        (Join-Path $studioRoot 'assets\fonts\LICENSE_DEJAVU')
    ) + @(Get-ChildItem -LiteralPath (Join-Path $studioRoot 'assets\licenses') -File |
          Sort-Object Name | Select-Object -ExpandProperty FullName)
    $studioLicenseInputs | ForEach-Object {
        "===== $([IO.Path]::GetFileName($_)) ====="
        Get-Content -LiteralPath $_ -Encoding UTF8
        ''
    } | Set-Content -LiteralPath $studioLicense -Encoding UTF8
    Compress-Archive -LiteralPath @($studioExe,$studioReadme,$studioLicense) `
        -DestinationPath (Join-Path $studioRoot 'dist\CV Studio-Windows.zip') -Force
    $studioChecksumFiles = @($studioExe,
        (Join-Path $studioRoot 'dist\CV Studio-Windows.zip'),$studioReadme,$studioLicense)
    $studioChecksumFiles | ForEach-Object {
        '{0}  {1}' -f (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant(),
                      [IO.Path]::GetFileName($_)
    } | Set-Content -LiteralPath (Join-Path $studioRoot 'dist\SHA256SUMS.txt') -Encoding UTF8
    $studioShortcutPath = Join-Path $studioRoot 'CV Studio.lnk'
    if (-not (Test-Path -LiteralPath $studioShortcutPath)) {
        $studioShell = New-Object -ComObject WScript.Shell
        $studioShortcut = $studioShell.CreateShortcut($studioShortcutPath)
        $studioShortcut.TargetPath = $studioExe
        $studioShortcut.WorkingDirectory = $studioRoot
        $studioShortcut.IconLocation = "$studioExe,0"
        $studioShortcut.Description = 'CV Studio - CV editor'
        $studioShortcut.Save()
    }
    Write-Output "Verified: $($studioResults.templates.Count) PDF designs, preview, photos, save and export."
    Write-Output "Built: $studioExe"
} finally {
    Pop-Location
}
