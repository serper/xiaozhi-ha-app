FROM python:3.12-alpine
ARG BUILD_VERSION=0.5.0
ARG BUILD_ARCH=aarch64
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && addgroup -S app && adduser -S -G app app
COPY bridge.py weather.py entrypoint.py ha_lights.py scheduler.py web_search.py ha_sensors.py /app/
CMD ["python", "/app/entrypoint.py"]
