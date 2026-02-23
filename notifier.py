import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

def send_update_email(to_email: str, keyword: str, tenders: list):
    """
    Sends an email notification with new tenders found.
    """
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP credentials not configured. Skipping email notification.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[TenderAlert] New tenders found for: {keyword}"
        msg["From"] = SMTP_USER
        msg["To"] = to_email

        # Build HTML email body
        tender_rows = ""
        for tender in tenders:
            title = tender.get("title", "Unknown Tender")
            url = tender.get("url", "#")
            tender_rows += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e2e8f0;">
                    <a href="{url}" style="color: #6366f1; text-decoration: none; font-weight: 600;">{title}</a>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e2e8f0;">
                    <a href="{url}" style="color: #64748b; font-size: 0.85em;">{url}</a>
                </td>
            </tr>
            """

        html_body = f"""
        <html>
        <body style="font-family: Inter, sans-serif; background: #f8fafc; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; padding: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <h2 style="color: #1e293b; margin-top: 0;">Tender Alerts Service</h2>
                <p style="color: #64748b;">We found the following new tenders matching your keyword <strong>'{keyword}'</strong>:</p>
                <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                    <thead>
                        <tr style="background: #f1f5f9;">
                            <th style="padding: 12px; text-align: left; color: #64748b; font-size: 0.85em; text-transform: uppercase;">Tender Title</th>
                            <th style="padding: 12px; text-align: left; color: #64748b; font-size: 0.85em; text-transform: uppercase;">Link</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tender_rows}
                    </tbody>
                </table>
                <p style="color: #94a3b8; font-size: 0.85em; margin-top: 30px;">Stay ahead of the competition!</p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
            logger.info(f"Email notification sent to {to_email}")

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
