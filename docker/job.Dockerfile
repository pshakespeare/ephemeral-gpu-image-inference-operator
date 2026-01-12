FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# Install Python and system dependencies
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3-pip \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch with CUDA support
RUN pip3 install --no-cache-dir \
    torch==2.1.0 \
    torchvision==0.16.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Install other dependencies
RUN pip3 install --no-cache-dir pillow

# Copy job code and requirements
WORKDIR /app
COPY src/job_image_infer/ ./job_image_infer/

# Set Python path
ENV PYTHONPATH=/app

# Default command (overridden by pod spec)
CMD ["python3", "-m", "job_image_infer.run_infer"]
