<#
.SYNOPSIS
    Start, stop or inspect the local Iceberg lakehouse stack (Windows native).

.DESCRIPTION
    The stack has three parts, all running as local processes:
      * catalog  - PostgreSQL cluster on port 15434 holding Iceberg metadata
      * storage  - MinIO server on port 9000 holding the Parquet data files
      * engine   - Spark, started on demand by the ingestion jobs

    Docker is not required; WSL2 is unavailable on this machine.

.EXAMPLE
    .\scripts\lakehouse.ps1 start
    .\scripts\lakehouse.ps1 status
    .\scripts\lakehouse.ps1 stop
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'restart', 'reset')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $RepoRoot 'data'
$MinioData = Join-Path $DataDir 'minio'
$CatalogData = Join-Path $env:LOCALAPPDATA 'cdp-iceberg-catalog'
$LogsDir = Join-Path $RepoRoot 'logs'

$CatalogPort = 15434
$StoragePort = 9000
$StorageConsolePort = 9001

$StorageUser = 'cdp-local'
$StoragePassword = 'cdp-local-storage'

$PostgresBin = 'C:\Program Files\PostgreSQL\18\bin'
$MinioExe = Join-Path $RepoRoot 'tools\bin\minio.exe'
$McExe = Join-Path $RepoRoot 'tools\bin\mc.exe'

function Write-Step($Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok($Message) { Write-Host "    OK  $Message" -ForegroundColor Green }
function Write-Warn($Message) { Write-Host "    --  $Message" -ForegroundColor Yellow }

function Test-TcpPort([int]$Port, [int]$TimeoutMs = 1500) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $task.Wait($TimeoutMs)) { $client.Close(); return $false }
        $client.Close()
        return $true
    } catch { return $false }
}

function Get-CatalogRunning {
    if (-not (Test-Path $CatalogData)) { return $false }
    $pidFile = Join-Path $CatalogData 'postmaster.pid'
    if (-not (Test-Path $pidFile)) { return $false }
    return (Test-TcpPort $CatalogPort)
}

function Start-Catalog {
    if (Get-CatalogRunning) {
        Write-Warn "Catalog already running on port $CatalogPort"
        return
    }
    if (-not (Test-Path $CatalogData)) {
        Write-Step 'Initialising the catalog PostgreSQL cluster'
        $pwFile = Join-Path $env:TEMP 'cdp-catalog-pw.txt'
        Set-Content -Path $pwFile -Value 'cdp-local-catalog' -NoNewline
        & "$PostgresBin\initdb.exe" -D $CatalogData -U cdp --pwfile="$pwFile" `
            --auth-local=scram-sha-256 --auth-host=scram-sha-256 | Out-Null
        Add-Content -Path (Join-Path $CatalogData 'postgresql.conf') `
            -Value "`nport = $CatalogPort`nlisten_addresses = '127.0.0.1'"
        Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    }

    Write-Step "Starting the catalog on port $CatalogPort"
    & "$PostgresBin\pg_ctl.exe" -D $CatalogData -l (Join-Path $CatalogData 'server.log') start | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-TcpPort $CatalogPort) { Write-Ok 'Catalog is accepting connections'; return }
        Start-Sleep -Milliseconds 500
    }
    throw "Catalog did not start; see $CatalogData\server.log"
}

function Start-Storage {
    if (Test-TcpPort $StoragePort) {
        Write-Warn "Storage already running on port $StoragePort"
        return
    }
    Write-Step "Starting MinIO on port $StoragePort"
    New-Item -ItemType Directory -Force -Path $MinioData, $LogsDir | Out-Null
    $env:MINIO_ROOT_USER = $StorageUser
    $env:MINIO_ROOT_PASSWORD = $StoragePassword
    Start-Process -FilePath $MinioExe `
        -ArgumentList 'server', $MinioData, '--address', "127.0.0.1:$StoragePort", `
                      '--console-address', "127.0.0.1:$StorageConsolePort" `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogsDir 'minio.out.log') `
        -RedirectStandardError (Join-Path $LogsDir 'minio.err.log') | Out-Null

    for ($i = 0; $i -lt 40; $i++) {
        if (Test-TcpPort $StoragePort) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-TcpPort $StoragePort)) { throw 'MinIO did not start; see logs\minio.err.log' }

    & $McExe alias set local "http://127.0.0.1:$StoragePort" $StorageUser $StoragePassword 2>&1 | Out-Null
    & $McExe mb --ignore-existing 'local/cdp' 2>&1 | Out-Null
    Write-Ok "Storage is live; bucket 'cdp' ready (console on $StorageConsolePort)"
}

function Stop-Storage {
    $procs = Get-Process -Name 'minio' -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force
        Write-Ok 'MinIO stopped'
    } else { Write-Warn 'MinIO was not running' }
}

function Stop-Catalog {
    if (Test-Path $CatalogData) {
        & "$PostgresBin\pg_ctl.exe" -D $CatalogData -m fast stop 2>&1 | Out-Null
        Write-Ok 'Catalog stopped'
    } else { Write-Warn 'Catalog was never initialised' }
}

function Show-Status {
    Write-Host ''
    Write-Host 'Lakehouse stack status' -ForegroundColor Cyan
    Write-Host '---------------------'
    if (Get-CatalogRunning) { Write-Ok "catalog  PostgreSQL  127.0.0.1:$CatalogPort" }
    else { Write-Warn "catalog  PostgreSQL  127.0.0.1:$CatalogPort  (stopped)" }
    if (Test-TcpPort $StoragePort) { Write-Ok "storage  MinIO        127.0.0.1:$StoragePort" }
    else { Write-Warn "storage  MinIO        127.0.0.1:$StoragePort  (stopped)" }
    Write-Host ''
    Write-Host "engine   Spark        started on demand by the ingestion jobs"
    Write-Host ''
}

switch ($Action) {
    'start' {
        Start-Catalog
        Start-Storage
        Show-Status
    }
    'stop' {
        Stop-Storage
        Stop-Catalog
    }
    'restart' {
        Stop-Storage; Stop-Catalog
        Start-Catalog; Start-Storage
        Show-Status
    }
    'reset' {
        Stop-Storage; Stop-Catalog
        Write-Step 'Removing the catalog cluster and the object storage'
        Remove-Item $CatalogData -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item $MinioData -Recurse -Force -ErrorAction SilentlyContinue
        Start-Catalog; Start-Storage
        Show-Status
    }
    'status' { Show-Status }
}
