FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Spacy models
RUN python -m spacy download en_core_web_sm
RUN python -m spacy download es_core_news_sm

COPY . .

CMD ["python", "main.py"]
