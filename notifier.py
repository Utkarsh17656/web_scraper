import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging

logger = logging.getLogger(__name__)

# Email Configuration (Use Environment Variables for security)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "") # Use App Password for Gmail

def send_update_email(target_email, keyword, new_tenders):
    """
    Sends an email notification with newly found tenders.
    """
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP credentials not set. Skipping email.")
        return False

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = target_email
    msg['Subject'] = f"🚀 {len(new_tenders)} New Tenders Found for keyword: '{keyword}'"

    # Create HTML table for the email
    table_rows = ""
    for tender in new_tenders:
        table_rows += f"""
        <tr>
            <td style='padding: 10px; border: 1px solid #ddd;'>{tender['title']}</td>
            <td style='padding: 10px; border: 1px solid #ddd;'><a href='{tender['url']}'>View Link</a></td>
        </tr>
        """

    html = f"""
    <html>
    <body>
        <h2>Tender Alerts Service</h2>
        <p>We found the following new tenders matching your keyword <b>'{keyword}'</b>:</p>
        <table style='width: 100%; border-collapse: collapse;'>
            <thead>
                <tr style='background-color: #f2f2f2;'>
                    <th style='padding: 10px; border: 1px solid #ddd;'>Tender Title</th>
                    <th style='padding: 10px; border: 1px solid #ddd;'>Action</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        <p>Stay ahead of the competition!</p>
    </body>
    </html>
    """

    msg.attach(MIMEText(html, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent successfully to {target_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False
