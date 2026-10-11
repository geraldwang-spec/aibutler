FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY requirements-exam-ai.txt .
RUN python -m venv /opt/exam-ai && /opt/exam-ai/bin/pip install --no-cache-dir -r requirements-exam-ai.txt
ENV EXAM_CPU_PYTHON=/opt/exam-ai/bin/python
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "1", "--threads", "4", "--timeout", "90", "-b", "0.0.0.0:5000", "app:create_app()"]
