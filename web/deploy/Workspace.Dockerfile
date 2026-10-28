# Build from the prepared review bundle, never from C:\Users or a live server tree.
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WORKSPACE_RUNTIME=1 PYTHONPATH=/app/backend:/app/planner-core
WORKDIR /app
COPY web/deploy/runtime-requirements.lock /app/runtime-requirements.lock
RUN pip install --no-cache-dir -r /app/runtime-requirements.lock
COPY web/backend/app /app/backend/app
COPY web/backend/workspace /app/backend/workspace
COPY planner /app/planner-core/planner
COPY access.py bitrix.py distribution.py /app/planner-core/
COPY web/frontend/dist /app/frontend-dist
# Run web as10001 or writer as10003 via Compose. Neither is root.
USER 10001:10020
CMD ["uvicorn","workspace.application:create_app","--factory","--host","0.0.0.0","--port","8000","--workers","1","--no-access-log","--no-proxy-headers"]

FROM runtime AS smoke
COPY web/deploy/linux_smoke.py /app/linux_smoke.py
CMD ["python","/app/linux_smoke.py"]
