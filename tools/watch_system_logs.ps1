# Read-only console monitor; closing it never stops the application or backup worker.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskReaders = @()
$taskLastSnapshot = ''

function Show-SnapshotStatus {
    $metadataPath = Join-Path $taskRoot 'instance\backups\standby.json'
    if (-not (Test-Path -LiteralPath $metadataPath)) { return }
    try {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($metadata.created_at -eq $script:taskLastSnapshot) { return }
        $time = [DateTimeOffset]::Parse($metadata.created_at)
        $local = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($time, 'Taipei Standard Time')
        $tables = @($metadata.rows.PSObject.Properties).Count
        Write-Host ('[快照] 最近備份：{0}（台灣時間），共 {1} 個資料表。' -f $local.ToString('yyyy-MM-dd HH:mm:ss'), $tables) -ForegroundColor Green
        $script:taskLastSnapshot = $metadata.created_at
    } catch {
        # Atomic snapshot publication can briefly replace the metadata file.
    }
}

Write-Host 'AI Butler 即時日誌（唯讀查看）' -ForegroundColor Cyan
Write-Host '同時查看標準輸出、請求／錯誤日誌，以及已建立的備援快照。'
Write-Host '定期備份會在服務啟動後依間隔執行；重新啟動服務會重新計時。'
Write-Host '關閉此視窗不會停止 5000 服務，也不會停止備份。'
Show-SnapshotStatus

try {
    foreach ($entry in @(@('輸出', 'ui-server.out.log'), @('請求', 'ui-server.err.log'))) {
        $path = Join-Path $taskRoot ('instance\' + $entry[1])
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $stream = [System.IO.File]::Open($path, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read, ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        $lines = New-Object 'System.Collections.Generic.Queue[string]'
        while (($line = $reader.ReadLine()) -ne $null) {
            $lines.Enqueue($line)
            if ($lines.Count -gt 20) { $null = $lines.Dequeue() }
        }
        foreach ($line in $lines) { Write-Host ('[{0}] {1}' -f $entry[0], $line) }
        $taskReaders += [PSCustomObject]@{Label=$entry[0]; Reader=$reader; Stream=$stream}
    }
    while ($true) {
        foreach ($entry in $taskReaders) {
            if ($entry.Stream.Length -lt $entry.Stream.Position) {
                $entry.Reader.DiscardBufferedData()
                $null = $entry.Stream.Seek(0, [System.IO.SeekOrigin]::Begin)
            }
            while (($line = $entry.Reader.ReadLine()) -ne $null) {
                Write-Host ('[{0}] {1}' -f $entry.Label, $line)
            }
        }
        Show-SnapshotStatus
        Start-Sleep -Milliseconds 500
    }
} finally {
    foreach ($entry in $taskReaders) { $entry.Reader.Dispose() }
}
