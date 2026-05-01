FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --default-timeout=120 --retries 5 -r requirements.txt

COPY . ./

CMD ["python", "esp32_bridge.py"]
