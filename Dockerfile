FROM node:22-bullseye AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_PORT=7860
ENV DEVICE_MODE=companion

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${APP_PORT:-7860}"]
