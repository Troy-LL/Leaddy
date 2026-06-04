# Level 3 — OpenClaw runtime (placeholder)
# Replace base image and install steps when OpenClaw is available in your environment.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir httpx
COPY skill.md .
# Example: RUN pip install openclaw && CMD ["openclaw", "serve", "skill.md"]
CMD ["echo", "OpenClaw runtime not bundled — mount skill.md into your OpenClaw install or extend this Dockerfile"]
