# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install python dependencies (every package ships a wheel, so no compiler in the image)
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

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
