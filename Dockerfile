FROM python:3.12-slim

WORKDIR /app

# Create data directory for persistent storage
RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY dashboard/ ./dashboard/

# Expose Dash port
EXPOSE 8050

CMD ["python", "main.py"]
