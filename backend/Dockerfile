FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ .
RUN useradd --create-home crm
USER crm
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
