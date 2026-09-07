FROM python:3.12-slim-bookworm

WORKDIR /srv
COPY backend/requirements.txt /srv/backend/requirements.txt
RUN pip install --no-cache-dir -r /srv/backend/requirements.txt
COPY backend /srv/backend
COPY vespa /srv/vespa
WORKDIR /srv/backend
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
