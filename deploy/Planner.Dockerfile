FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-planner.txt requirements-planner.lock.txt ./
RUN pip install --no-cache-dir -r requirements-planner.txt \
    && groupadd --gid 10001 planner \
    && useradd --uid 10001 --gid planner --no-create-home --shell /usr/sbin/nologin planner
COPY access.py ./
COPY planner ./planner
COPY miniapp/dist ./miniapp/dist
COPY frontend-build.json ./frontend-build.json
RUN python -c "from pathlib import Path; from planner.frontend import validate_static; validate_static(Path('/app/miniapp/dist'), Path('/app/frontend-build.json'))"
USER 10001:10001
CMD ["python", "-m", "uvicorn", "planner.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
