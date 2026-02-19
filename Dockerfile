# Use the official Playwright Docker image which includes Python and browsers
# This ensures all system dependencies for the browser are present
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Explicitly install the Chromium browser for Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy the rest of the application code
COPY . .

# Expose the port the app runs on (Render sets PORT env var)
# We default to 10000 if not set, but Render will override it
ENV PORT=10000

# Run the application
# Use shell form to allow variable expansion for $PORT
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
