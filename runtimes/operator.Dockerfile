FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir kopf kubernetes pydantic

# Copy source code
COPY src/ ./src/

# Set Python path
ENV PYTHONPATH=/app

# Run operator
CMD ["python", "-m", "operator.main"]
