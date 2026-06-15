# Atualização diária da base de FIDCs (rodar via Agendador de Tarefas do Windows).
# Uso manual:  powershell -ExecutionPolicy Bypass -File .\run_daily.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$log = Join-Path $PSScriptRoot "data\pipeline.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

"[{0}] Iniciando atualizacao FIDC" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
python -m fidc.pipeline 2>&1 | Tee-Object -FilePath $log -Append

# Sincroniza os parquets com o Hugging Face Dataset (mantém o Space atualizado)
"[{0}] Sincronizando com Hugging Face Dataset..." -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
$env:SSL_CERT_FILE = "$env:USERPROFILE\ca-bundle-windows.pem"
$env:REQUESTS_CA_BUNDLE = "$env:USERPROFILE\ca-bundle-windows.pem"
python -c "
from huggingface_hub import HfApi
import pathlib
api = HfApi()
base = pathlib.Path(r'$PSScriptRoot\data\processed')
for f in ['fidc_consolidado.parquet', 'fidc_cotas.parquet', 'cdi_mensal.parquet']:
    p = base / f
    if p.exists():
        api.upload_file(
            path_or_fileobj=str(p),
            path_in_repo=f,
            repo_id='claudiormpaes/fidc-dados',
            repo_type='dataset',
            commit_message=f'Atualizacao diaria automatica: {f}'
        )
        print(f'HF Dataset: {f} atualizado')
" 2>&1 | Tee-Object -FilePath $log -Append

"[{0}] Concluido" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
