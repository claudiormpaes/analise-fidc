FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Assa os dados do HF DENTRO da imagem (no build), eliminando o download lento e
# rate-limited a cada cold start no Cloud Run. Os dados ficam tão atuais quanto o
# último deploy (o ETL diário continua atualizando o HF; basta redeployar p/ refrescar).
RUN python -c "import os,shutil; from huggingface_hub import hf_hub_download; os.makedirs('data/processed', exist_ok=True); [shutil.copy(hf_hub_download(repo_id='claudiormpaes/fidc-dados', filename=f, repo_type='dataset'), os.path.join('data/processed', f)) for f in ['fidc_consolidado.parquet','fidc_cotas.parquet','fidc_carteira.parquet','cdi_mensal.parquet','ipca_mensal.parquet','selic_mensal.parquet']]"

# O Cloud Run injeta a porta em $PORT (8080). No HF Spaces a var não existe,
# então caímos no padrão 7860. Assim o mesmo Dockerfile serve nos dois.
# Injeta o Google Analytics (GT-P8Z92S69) no index.html do Streamlit
RUN python -c 'import streamlit,os; p=os.path.join(os.path.dirname(streamlit.__file__),"static","index.html"); s=open(p,encoding="utf-8").read(); tag="<script async src=\x27https://www.googletagmanager.com/gtag/js?id=GT-P8Z92S69\x27></script><script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag(\x27js\x27,new Date());gtag(\x27config\x27,\x27GT-P8Z92S69\x27);</script>"; open(p,"w",encoding="utf-8").write(s.replace("<head>","<head>"+tag,1))'

EXPOSE 8080

CMD streamlit run app.py \
    --server.port=${PORT:-7860} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
