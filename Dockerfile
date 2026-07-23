FROM python:3.12-slim

# tesseract-ocr — распознавание текста на скриншотах оплаты (rus+eng);
# Railpack не умеет ставить системные пакеты, поэтому здесь Dockerfile.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "vicegram_bot.py"]
