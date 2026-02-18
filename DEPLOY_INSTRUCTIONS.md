# Deploying to Render

This guide helps you deploy your scraper tool to [Render.com](https://render.com).

## 1. Push Code to GitHub
1.  Initialize git if you haven't: `git init`
2.  Add files: `git add .`
3.  Commit: `git commit -m "Initial commit"`
4.  Create a new repository on GitHub.
5.  Link and push:
    ```bash
    git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
    git push -u origin main
    ```

## 2. Deploy on Render
1.  Log in to [Render Dashboard](https://dashboard.render.com).
2.  Click **New +** -> **Web Service**.
3.  Connect your GitHub repository.
4.  Choose **Docker** as the Runtime (it should detect the `Dockerfile` automatically).
5.  Set the **Name** (e.g., `web-scraper`).
6.  (Optional) Set Environment Variables if needed.
7.  Click **Create Web Service**.

## 3. Configuration Details
-   **Port**: The app listens on port `10000` by default (Render sets this via `$PORT`).
-   **Docker**: Uses the official Playwright image for stability.
-   **Performance**: Since Playwright browsers are resource-intensive, consider upgrading from the Free tier if scraping fails due to memory limits, though lightweight tasks should work fine.

## Note on Memory
Playwright can consume significant RAM. On Render's free tier (512MB), you might encounter occasional crashes if scraping very heavy sites or using high depth. Limiting `max_depth` and concurrency helps.
