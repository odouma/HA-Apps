import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


def send_report_email(email_settings, recipients, subject, body_text, pdf_bytes, filename):
    """Verstuurt een e-mail met PDF-bijlage. Retourneert (success, message)."""
    host = email_settings.get("smtp_host")
    if not host:
        return False, "Geen SMTP-server ingesteld bij E-mail instellingen."

    if not recipients:
        return False, "Geen ontvangers opgegeven."

    from_address = email_settings.get("from_address") or email_settings.get("username")
    if not from_address:
        return False, "Geen afzenderadres ingesteld."

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_text, "plain"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    port = int(email_settings.get("smtp_port", 587))
    encryption = email_settings.get("encryption", "starttls")
    username = email_settings.get("username")
    password = email_settings.get("password")

    try:
        if encryption == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)

        with server:
            if encryption == "starttls":
                server.starttls()
            if username:
                server.login(username, password or "")
            server.sendmail(from_address, recipients, msg.as_string())

        return True, f"E-mail verzonden naar {', '.join(recipients)}."

    except Exception as e:  # noqa: BLE001 - alle SMTP-fouten netjes teruggeven
        return False, f"Verzenden mislukt: {e}"
