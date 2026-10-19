FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY cos ./cos
RUN pip install --no-cache-dir .

ENV COS_DATA_DIR=/data \
    COS_HOST=0.0.0.0 \
    COS_PORT=8700
VOLUME /data
EXPOSE 8700

HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8700/health')"
CMD ["cos", "serve"]
