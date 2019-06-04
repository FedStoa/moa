import importlib
import os
import smtplib

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

try:
    message = (f"From: {c.MAIL_DEFAULT_SENDER}\n" +
               f"To: {c.MAIL_TO}\n" +
               f"Subject: Moa Email Test\n" +
               f"\n" +
               f"Test Message\n" +
               f"\n"
               )

    smtpObj = smtplib.SMTP(c.MAIL_SERVER, c.MAIL_PORT)
    smtpObj.ehlo()
    smtpObj.starttls()
    smtpObj.login(c.MAIL_USERNAME, password=c.MAIL_PASSWORD)
    smtpObj.sendmail(c.MAIL_DEFAULT_SENDER, [c.MAIL_TO], message)
    smtpObj.quit()

except smtplib.SMTPException as e:
    print(e)

except TimeoutError as e:
    print(e)
