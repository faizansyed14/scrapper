FROM python:3.11-slim

# 1. Update OS and install Playwright OS dependencies as root
RUN apt-get update && apt-get install -y wget gnupg && rm -rf /var/lib/apt/lists/*
RUN pip install playwright
RUN playwright install-deps chromium

# 2. Set up the non-root user as required by Hugging Face
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# 3. Copy requirements and install Python dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Install the actual Headless Chromium browser as the non-root user
RUN playwright install chromium

# 5. Copy the rest of the application
COPY --chown=user . /app

# 6. Configure Hugging Face port
ENV PORT=7860
EXPOSE 7860

# 7. Start the application
WORKDIR /app/scraper_ui
CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:app", "--timeout", "120", "--workers", "2", "--threads", "4"]
