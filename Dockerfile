# Use official Python runtime
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system tools needed for legacy Word .doc extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies FIRST (Optimizes Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port for GCP Cloud Run (Default is 8080)
EXPOSE 8080

# Run Streamlit on the specified PORT
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true"]
