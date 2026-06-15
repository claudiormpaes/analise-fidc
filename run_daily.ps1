# Atualização diária da base de FIDCs (rodar via Agendador de Tarefas do Windows).
# Uso manual:  powershell -ExecutionPolicy Bypass -File .\run_daily.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$log = Join-Path $PSScriptRoot "data\pipeline.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

"[{0}] Iniciando atualizacao FIDC" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
python -m fidc.pipeline 2>&1 | Tee-Object -FilePath $log -Append
"[{0}] Concluido" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
