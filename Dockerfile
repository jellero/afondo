FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
COPY config/source_candidates.json ./config/source_candidates.json
RUN pip install --no-cache-dir .
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["uvicorn", "afondo.main:app", "--host", "0.0.0.0", "--port", "8000"]
