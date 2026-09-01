FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Runtime state is a volume at /srv/ci — never copied into the image.
WORKDIR /app
CMD ["python", "-c", "from yahoo import healthcheck; print(healthcheck())"]
