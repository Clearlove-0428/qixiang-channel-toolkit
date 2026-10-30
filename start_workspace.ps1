param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$dataRoot = if ($env:QIXIANG_DATA_ROOT) { [IO.Path]::GetFullPath($env:QIXIANG_DATA_ROOT) } else { Join-Path $projectRoot '调研资料库' }
$logRoot = Join-Path $dataRoot '运行日志'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$url = 'http://127.0.0.1:8765'
try {
    $ready = $false
    try { $health = Invoke-RestMethod ($url + '/api/health') -TimeoutSec 2; $ready = $health.app -eq 'qixiang_research_library_v2' } catch { }
    if (-not $ready) {
        if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先运行 setup.ps1 安装依赖。' }
        $program = Join-Path $projectRoot '频道文本工具/research_library.py'
        $arguments = '-X utf8 "' + $program + '" --root "' + $dataRoot + '" serve --no-browser'
        Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'server.stdout.log') -RedirectStandardError (Join-Path $logRoot 'server.stderr.log')
        for ($attempt=0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Milliseconds 200
            try { $health = Invoke-RestMethod ($url + '/api/health') -TimeoutSec 2; if ($health.app -eq 'qixiang_research_library_v2') { $ready=$true; break } } catch { }
        }
    }
    if (-not $ready) { throw ('启动失败，请查看：' + $logRoot) }
    $state = Invoke-RestMethod ($url + '/api/state') -TimeoutSec 5
    if ([IO.Path]::GetFullPath($state.library_root) -ne [IO.Path]::GetFullPath($dataRoot)) { throw '8765端口已有另一个资料库。请用命令行指定其他端口，或先关闭原服务。' }
    if (-not $NoBrowser) { Start-Process $url }
    Write-Host ('Workspace ready: ' + $url)
} catch { Write-Error $_; exit 1 }
