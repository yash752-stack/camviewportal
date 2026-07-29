# ============================================================
#  CamView / Compliance_Portal - extract and run (end to end)
# ============================================================
# Extracts CamView_CompliancePortal_Complete.zip to your Desktop and
# launches it. First run builds the Python environment from the bundled
# wheels (offline, under a minute) and needs Python 3.12 or 3.13 already
# on this machine (the bundle's wheels are built for those two versions
# only) - if it's missing, run.bat will say so and point to the
# installer; run this script again afterward.

$Zip  = Get-ChildItem "$HOME\Downloads" -Filter "CamView_CompliancePortal_Complete*.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $Zip) {
    Write-Host "Could not find CamView_CompliancePortal_Complete.zip in $HOME\Downloads" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "Found: $Zip" -ForegroundColor Green

$Dest = "$HOME\Desktop\Compliance_Portal"
if (Test-Path $Dest) {
    Write-Host "$Dest already exists - remove or rename it first, then re-run this script." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Extracting to $Dest ..." -ForegroundColor Cyan
Expand-Archive -Path $Zip -DestinationPath "$HOME\Desktop" -Force

Write-Host "Starting the portal (first run builds the environment, under a minute)..." -ForegroundColor Cyan
Set-Location $Dest
cmd /c run.bat
