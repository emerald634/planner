FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ACCESS_DB_PATH=/data/access.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 bot \
    && useradd --uid 10001 --gid bot --no-create-home --shell /usr/sbin/nologin bot
COPY access.py bitrix.py bot.py config.py distribution.py keyboards.py reminders.py ./
COPY planner/__init__.py planner/distribution_queue.py ./planner/
USER 10001:10001
CMD ["python", "bot.py"]
