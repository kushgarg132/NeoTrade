# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
# We need gcc and other build tools for TA-Lib
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The commit this image was built from, shown in the handbook (backend/system/status.py).
ARG GIT_SHA=
ENV GIT_SHA=$GIT_SHA

# Copy project into a subdirectory to preserve package imports
COPY . ./backend

# Set PYTHONPATH to include the /app directory
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
