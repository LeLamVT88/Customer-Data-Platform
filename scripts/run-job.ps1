<#
.SYNOPSIS
    Run a lakehouse job with the correct Java, Hadoop and Spark environment.

.DESCRIPTION
    PySpark on Windows needs three environment variables that are easy to get
    wrong:
      * JAVA_HOME must point at JDK 17 (the default JDK 21 breaks Spark 3.5)
      * HADOOP_HOME must point at a directory containing bin\winutils.exe
      * SPARK_LOCAL_IP avoids hostname resolution failures in local mode

.EXAMPLE
    .\scripts\run-job.ps1 src\pipelines\lakehouse\check_environment.py
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Script,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$JobArgs
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Jdk17 = 'C:\Program Files\Java\jdk-17'
$HadoopHome = Join-Path $RepoRoot 'tools\hadoop'

if (-not (Test-Path $Python)) { throw "Virtual environment not found: $Python" }
if (-not (Test-Path $Script)) { throw "Script not found: $Script" }
if (-not (Test-Path $Jdk17)) { throw "JDK 17 not found: $Jdk17" }

$env:JAVA_HOME = $Jdk17
$env:HADOOP_HOME = $HadoopHome
$env:PATH = "$Jdk17\bin;$HadoopHome\bin;$env:PATH"
$env:SPARK_LOCAL_IP = '127.0.0.1'
$env:PYSPARK_PYTHON = $Python
$env:PYSPARK_DRIVER_PYTHON = $Python

# Spark logs to stderr; with $ErrorActionPreference = 'Stop' PowerShell would
# treat every log line as a terminating error. Relax it just around the call.
$ErrorActionPreference = 'Continue'
& $Python $Script @JobArgs
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
exit $code
