FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir openai httpx
COPY simple_agent.py .
ENTRYPOINT ["python", "simple_agent.py"]
