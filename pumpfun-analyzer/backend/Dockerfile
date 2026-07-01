FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# NOT: build-essential (C derleyici) KURULMAZ. Kullandığımız tüm Python paketleri
# (cryptography, psycopg[binary], uvicorn[standard]…) hazır manylinux wheel olarak
# gelir; derleyici gerekmez. Bu, build'i çok hızlandırır ve belleği korur.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Trading keystore için veri dizini
RUN mkdir -p /app/data

EXPOSE 8000

# Migrationları uygula ve API'yi başlat
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
