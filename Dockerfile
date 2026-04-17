FROM python:3.11-slim

# Set up working directory
WORKDIR /app

# Install system dependencies required for Playwright/Headless Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies file
COPY requirements.txt .

# Install python packages
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser dependencies (Chromium only to save space)
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy all application files to container
COPY . .

# Hugging Face requires running on port 7860
ENV PORT=7860
EXPOSE 7860

# Adjust working directory to where the Flask app lives
WORKDIR /app/scraper_ui

# Run the flask server using gunicorn for production
CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:app", "--timeout", "120", "--workers", "2", "--threads", "4"]
