# Atualização diária da base de FIDCs (rodar via Agendador de Tarefas do Windows).
# Uso manual:  powershell -ExecutionPolicy Bypass -File .\run_daily.ps1
$ErrorActionPreference = "Continue"   # nao interrompe o script em erros nao-fatais
Set-Location -Path $PSScriptRoot

$log = Join-Path $PSScriptRoot "data\pipeline.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

"[{0}] Iniciando atualizacao FIDC" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
python -m fidc.pipeline 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) {
    "[{0}] ERRO no pipeline (exit $LASTEXITCODE) — abortando sync HF" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
    exit $LASTEXITCODE
}

# Sincroniza os parquets com o Hugging Face Dataset (mantém o Space atualizado)
"[{0}] Sincronizando com Hugging Face Dataset..." -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
$env:SSL_CERT_FILE = "$env:USERPROFILE\ca-bundle-windows.pem"
$env:REQUESTS_CA_BUNDLE = "$env:USERPROFILE\ca-bundle-windows.pem"
python -c @"
from huggingface_hub import HfApi
import pathlib, sys
api = HfApi()
base = pathlib.Path(r'$PSScriptRoot\data\processed')
erros = []
for f in ['fidc_consolidado.parquet', 'fidc_cotas.parquet', 'cdi_mensal.parquet',
          'ipca_mensal.parquet', 'selic_mensal.parquet', 'fidc_carteira.parquet']:
    p = base / f
    if not p.exists():
        print(f'AVISO: {f} nao encontrado, pulando')
        continue
    try:
        api.upload_file(
            path_or_fileobj=str(p),
            path_in_repo=f,
            repo_id='claudiormpaes/fidc-dados',
            repo_type='dataset',
            commit_message=f'Atualizacao diaria: {f}'
        )
        print(f'OK: {f} enviado ao HF Dataset')
    except Exception as e:
        print(f'ERRO ao enviar {f}: {e}')
        erros.append(f)
if erros:
    print(f'Falha em {len(erros)} arquivo(s): {erros}')
    sys.exit(1)
"@ 2>&1 | Tee-Object -FilePath $log -Append

if ($LASTEXITCODE -eq 0) {
    # Reinicia o Space para carregar os dados atualizados
    "[{0}] Reiniciando HF Space..." -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
    python -c @"
from huggingface_hub import HfApi
HfApi().restart_space('claudiormpaes/analise-fidc')
print('Space reiniciado.')
"@ 2>&1 | Tee-Object -FilePath $log -Append
}

"[{0}] Concluido" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $log -Append
