---
title: Scrapling Scraper Dashboard
emoji: 🕷️
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Scrapling UI Dashboard
A custom headless Web Scraper dashboard powered by Flask, Scrapling, and Playwright.

## Features
- **Headless Chrome**: Bypasses Turnstile and Cloudflare with stealth browsers automatically.
- **Dynamic Site Parsing**: Pulls real-time job data from Naukrigulf and LinkedIn.
- **Smart Sorting**: Instantly sort by recent data utilizing relative-time mapping.
- **Excel Export**: Download datasets instantly.

## Quick Start (New Laptop Setup)

If you pull this repository on a new machine, open your terminal in the project folder and run the following commands in order:

### 1. Set up Virtual Environment (Windows)
```bash
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Playwright Browsers
*This is required for the headless scraper to work.*
```bash
playwright install
```

### 4. Set up Environment Variables
```bash
cp .env.example .env
```
*(You can manually rename `.env.example` to `.env` if `cp` is not available).*

### 5. Run the Application
```bash
python scraper_ui/app.py
```
Open `http://localhost:5000` in your browser.
