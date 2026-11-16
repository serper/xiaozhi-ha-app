ARG BUILD_FROM=python:3.12-alpine
FROM ${BUILD_FROM}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && addgroup -S app && adduser -S -G app app
COPY bridge.py weather.py entrypoint.py /app/
CMD ["python", "/app/entrypoint.py"]
