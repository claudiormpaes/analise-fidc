FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O Cloud Run injeta a porta em $PORT (8080). No HF Spaces a var não existe,
# então caímos no padrão 7860. Assim o mesmo Dockerfile serve nos dois.
EXPOSE 8080

CMD streamlit run app.py \
    --server.port=${PORT:-7860} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
