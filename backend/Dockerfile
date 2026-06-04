FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:////app/data/leads.db

RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
