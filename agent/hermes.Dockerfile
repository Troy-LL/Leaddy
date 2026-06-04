# Level 3 — Hermes runtime (placeholder)
# Replace base image and install steps when Hermes is available in your environment.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir httpx
COPY skill.md .
# Example: RUN pip install hermes-agent && CMD ["hermes", "serve", "skill.md"]
CMD ["echo", "Hermes runtime not bundled — mount skill.md into your Hermes install or extend this Dockerfile"]
