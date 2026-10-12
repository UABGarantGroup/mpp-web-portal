<#
.SYNOPSIS
    Provisions a Generation 2 Hyper-V Virtual Machine optimized for Ubuntu Server 24.04 / 22.04 LTS
    to host the MS Project Centralized Resource & Template Hub (MPP Web Portal).

.DESCRIPTION
    Run this script as Administrator on your Windows Server / Windows 11 Hyper-V Host.
    It creates the VM, configures vCPU, RAM, Dynamic VHDX, Secure Boot (MicrosoftUEFICertificateAuthority for Linux),
    attaches the Ubuntu Server ISO, and enables Hyper-V Guest Integration Services.

.EXAMPLE
    .\Create-HyperV-LinuxVM.ps1 -VMName "MPP-Web-Portal-VM" -SwitchName "Default Switch" -IsoPath "C:\ISOs\ubuntu-24.04.1-live-server-amd64.iso"
#>

param(
    [string]$VMName = "MPP-Web-Portal-VM",
    [string]$SwitchName = "Default Switch",
    [string]$VMPath = "C:\Hyper-V\Virtual Machines",
    [string]$IsoPath = "",
    [int]$ProcessorCount = 2,
    [int64]$MemoryStartupBytes = 4GB,
    [int64]$VHDSizeBytes = 40GB
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Creating Hyper-V Linux VM: $VMName" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Ensure target directory exists
$VHDPath = Join-Path -Path $VMPath -ChildPath "$VMName\$VMName.vhdx"
if (-not (Test-Path $VMPath)) {
    New-Item -ItemType Directory -Path $VMPath -Force | Out-Null
}

# 1. Create Generation 2 VM with Dynamic VHDX
New-VM -Name $VMName `
       -Generation 2 `
       -MemoryStartupBytes $MemoryStartupBytes `
       -NewVHDPath $VHDPath `
       -NewVHDSizeBytes $VHDSizeBytes `
       -Path $VMPath `
       -SwitchName $SwitchName | Out-Null

# 2. Configure vCPU and Fixed/Dynamic Memory
Set-VMProcessor -VMName $VMName -Count $ProcessorCount
Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $false

# 3. Configure Secure Boot for Ubuntu Linux (MicrosoftUEFICertificateAuthority)
Set-VMFirmware -VMName $VMName -EnableSecureBoot On -SecureBootTemplate "MicrosoftUEFICertificateAuthority"

# 4. Enable Hyper-V Linux Integration Services (Time Sync, Heartbeat, Shutdown, Key-Value Pair, Guest File Copy)
Enable-VMIntegrationService -VMName $VMName -Name "Guest Service Interface" -ErrorAction SilentlyContinue

# 5. Configure Automatic Start & Stop Actions for Production Server
Set-VM -Name $VMName -AutomaticStartAction Start -AutomaticStopAction ShutDown -CheckpointType Production

# 6. Attach Ubuntu Server LTS ISO if provided and set as first boot device
if ($IsoPath -and (Test-Path $IsoPath)) {
    Add-VMDvdDrive -VMName $VMName -Path $IsoPath
    $dvd = Get-VMDvdDrive -VMName $VMName
    Set-VMFirmware -VMName $VMName -FirstBootDevice $dvd
    Write-Host "[OK] Attached Ubuntu ISO: $IsoPath (Set as First Boot Device)" -ForegroundColor Green
} else {
    Write-Host "[INFO] No ISO attached yet. Attach your Ubuntu 24.04 LTS ISO in Hyper-V Manager before starting." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Hyper-V VM '$VMName' created successfully!" -ForegroundColor Green
Write-Host "  - Generation: 2 (UEFI + Linux Secure Boot)"
Write-Host "  - vCPUs:      $ProcessorCount"
Write-Host "  - RAM:        $($MemoryStartupBytes / 1GB) GB"
Write-Host "  - Disk:       $($VHDSizeBytes / 1GB) GB ($VHDPath)"
Write-Host "  - Switch:     $SwitchName"
Write-Host ""
Write-Host "Next step: Start the VM (`Start-VM -Name '$VMName'`), install Ubuntu Server LTS, and run deploy/ubuntu-vm-install.sh inside the VM." -ForegroundColor Cyan
