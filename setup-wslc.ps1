[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPositionalParameters', '', Justification = 'Invoke-Wslc forwards native CLI arguments unchanged.')]
param(
    [ValidateSet('up', 'down', 'status')]
    [string]$Action = 'up'
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Network = 'osdu-iceberg-net'
$Volume = 'osdu-seaweed-data'
$Label = 'io.osdu.iceberg.quickstart=wslc'

function Invoke-Wslc {
    & wslc @args
    if ($LASTEXITCODE -ne 0) {
        throw "wslc $($args -join ' ') failed (exit $LASTEXITCODE)."
    }
}

function Invoke-StackContainer {
    param([string]$Name, [string[]]$RunArguments)

    $Existing = Invoke-Wslc list --all --quiet --filter "name=^/$Name$"
    if ($Existing) {
        $Container = @(Invoke-Wslc inspect $Name | ConvertFrom-Json)[0]
        if ($Container.Config.Labels.'io.osdu.iceberg.quickstart' -ne 'wslc') {
            throw "Container '$Name' already exists and is not managed by this script."
        }
        if (-not $Container.State.Running) {
            Invoke-Wslc start $Name | Out-Host
        }
    } else {
        Invoke-Wslc run -d --name $Name --label $Label --network $Network @RunArguments | Out-Host
    }
}

function Wait-Http {
    param([string]$Uri, [string]$Container)

    $Deadline = (Get-Date).AddSeconds(180)
    do {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
            if ($Response.StatusCode -eq 200) { return }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $Deadline)
    throw "Timed out waiting for $Uri. Check: wslc logs $Container"
}

Get-Command wslc -ErrorAction Stop | Out-Null

if ($Action -eq 'status') {
    Invoke-Wslc list --all --filter "label=$Label"
    exit
}

if ($Action -eq 'down') {
    # Only remove this stack's containers, never unrelated WSLC workloads or data.
    foreach ($Name in @('osdu-spark-iceberg', 'osdu-iceberg-rest', 'osdu-seaweedfs')) {
        $Existing = Invoke-Wslc list --all --quiet --filter "label=$Label" --filter "name=^/$Name$"
        if ($Existing) {
            Invoke-Wslc stop $Name | Out-Host
            Invoke-Wslc remove $Name | Out-Host
        }
    }
    Write-Output "Containers removed. Data remains in $Volume and the repository's warehouse/notebooks folders."
    exit
}

Invoke-Wslc build -t osdu-spark-iceberg:local (Join-Path $Root 'spark-iceberg') | Out-Host

if (-not (Invoke-Wslc network list --quiet --filter "name=^$Network$")) {
    Invoke-Wslc network create $Network | Out-Host
}
if (-not (Invoke-Wslc volume list --quiet --filter "name=^$Volume$")) {
    Invoke-Wslc volume create $Volume | Out-Host
}
foreach ($Directory in @('spark', 'warehouse', 'notebooks')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $Directory) | Out-Null
}

$Config = (Invoke-Wslc run --rm --entrypoint cat osdu-spark-iceberg:local /opt/spark/conf/spark-defaults.conf) -join "`n"
$Config = $Config.Replace('http://minio:9000', 'http://seaweedfs:9000')
$Config += "`nspark.sql.catalog.demo.s3.path-style-access true`n"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Root 'spark\spark-defaults.conf'), $Config, $Utf8)

$Aws = @(
    '-e', 'AWS_ACCESS_KEY_ID=admin',
    '-e', 'AWS_SECRET_ACCESS_KEY=password',
    '-e', 'AWS_REGION=us-east-1',
    '-e', 'AWS_REQUEST_CHECKSUM_CALCULATION=when_required',
    '-e', 'AWS_RESPONSE_CHECKSUM_VALIDATION=when_required'
)

Invoke-StackContainer 'osdu-seaweedfs' @(
    '--network-alias', 'seaweedfs', '--hostname', 'seaweedfs',
    '-p', '127.0.0.1:9000:9000', '-p', '127.0.0.1:9333:9333', '-p', '127.0.0.1:8889:8888',
    '-v', "${Volume}:/data",
    '--mount', "type=bind,source=$Root\seaweedfs\s3.json,target=/etc/seaweedfs/s3.json,readonly",
    'chrislusf/seaweedfs:latest', 'server', '-dir=/data', '-ip=seaweedfs', '-ip.bind=0.0.0.0',
    '-master.volumeSizeLimitMB=1024', '-s3', '-s3.port=9000', '-s3.config=/etc/seaweedfs/s3.json'
)

$CreateBucket = @'
set -eu
attempt=0
until curl -s --max-time 5 -o /dev/null http://seaweedfs:9000/; do
  attempt=$((attempt + 1))
  if [ $attempt -ge 60 ]; then echo 'SeaweedFS S3 did not start' >&2; exit 1; fi
  sleep 2
done
curl -fsS --max-time 30 --aws-sigv4 aws:amz:us-east-1:s3 --user admin:password --head http://seaweedfs:9000/warehouse \
  || curl -fsS --max-time 30 --aws-sigv4 aws:amz:us-east-1:s3 --user admin:password -X PUT http://seaweedfs:9000/warehouse
echo 'bucket warehouse ready'
'@
$CreateBucket = $CreateBucket.Replace("`r", '')
Invoke-Wslc run --rm --network $Network --entrypoint sh curlimages/curl:latest -c $CreateBucket | Out-Host

Invoke-StackContainer 'osdu-iceberg-rest' ($Aws + @(
    '--network-alias', 'rest', '-p', '127.0.0.1:8181:8181',
    '-e', 'CATALOG_WAREHOUSE=s3://warehouse/',
    '-e', 'CATALOG_IO__IMPL=org.apache.iceberg.aws.s3.S3FileIO',
    '-e', 'CATALOG_S3_ENDPOINT=http://seaweedfs:9000',
    '-e', 'CATALOG_S3_PATH__STYLE__ACCESS=true',
    'apache/iceberg-rest-fixture:1.8.1'
))
Wait-Http 'http://localhost:8181/v1/config' 'osdu-iceberg-rest'

Invoke-StackContainer 'osdu-spark-iceberg' ($Aws + @(
    '-p', '127.0.0.1:8888:8888', '-p', '127.0.0.1:8080:8080',
    '-p', '127.0.0.1:10000:10000', '-p', '127.0.0.1:10001:10001',
    '--mount', "type=bind,source=$Root\warehouse,target=/home/iceberg/warehouse",
    '--mount', "type=bind,source=$Root\notebooks,target=/home/iceberg/notebooks/notebooks",
    '--mount', "type=bind,source=$Root\spark\spark-defaults.conf,target=/opt/spark/conf/spark-defaults.conf,readonly",
    '-e', 'PYICEBERG_CATALOG__DEFAULT__URI=http://rest:8181',
    '-e', 'PYICEBERG_CATALOG__DEFAULT__S3__ENDPOINT=http://seaweedfs:9000',
    '-e', 'PYICEBERG_CATALOG__DEFAULT__S3__ACCESS_KEY_ID=admin',
    '-e', 'PYICEBERG_CATALOG__DEFAULT__S3__SECRET_ACCESS_KEY=password',
    '-e', 'PYICEBERG_CATALOG__DEFAULT__S3__REGION=us-east-1',
    'osdu-spark-iceberg:local'
))
Wait-Http 'http://localhost:8888' 'osdu-spark-iceberg'
Write-Output 'Ready: Jupyter http://localhost:8888 | Iceberg REST http://localhost:8181/v1/config | Filer http://localhost:8889'
