
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

EXPOSE 8000

# Shell form (not the JSON-array exec form): JSON form does NOT expand env vars,
# and hosts like Render/Railway/Fly inject the port to bind as $PORT. Binding a
# hardcoded 8000 there means the health check never connects and the deploy is
# marked failed. ${PORT:-8000} falls back to 8000 so local `docker run -p 8000:8000`
# keeps working unchanged.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]