FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "-k", "gevent", "--worker-connections", "256", "--bind", "0.0.0.0:5000", "app:app"]
