import os
import base64
import pickle
import pandas as pd 
from flask import session
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

COMPANY_LOGO = "app/static/zuna1_logo.png"  
COMPLIANCE_IMAGE = "app/static/image.png"  
GOOGLE_CALENDAR_URL = "https://calendar.google.com/calendar/u/1/r?cid=c_823dd2a595fb4f5edf52b6aa0328fc534d98718bb0e10987d7bf11bd8d8cefbb@group.calendar.google.com"
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfx0MRqVfOZonFoY9tDc1G8iM76qIBs2Tg3TvbJcrXAy3vdFQ/viewform"
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

def authenticate_gmail():
    """Authenticates with Gmail API and returns service object."""
    creds = None
    token_path = "token.pkl"

    if os.path.exists(token_path):
        with open(token_path, "rb") as token_file:
            creds = pickle.load(token_file)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as token_file:
            pickle.dump(creds, token_file)

    return build("gmail", "v1", credentials=creds)

def process_files(excel_path, contacts_path):
    """Reads Excel and contacts files, processes compliance data, and returns filtered data."""
    try:
        _, file_extension = os.path.splitext(contacts_path)

        contact_columns = ["Entity Name", "Contact Person", "Email", "Country", 
                           "TDS", "TCS", "Advance Tax", "ITR", "GST", "GST - QRMP", "IEC", "PF", "ESI", 
                           "PT - Karnataka", "LWF", "MCA", "MCA - LLP", "FEMA", "FEMA - ECB", "STPI", 
                           "GST - OIDAR", "GST - Job Work", "GST - Composition", "GST - TDS/TCS", 
                           "GST - NRTP", "GST - ISD", "Equilisation Levy", "IRS", "DDC", "CFTB", 
                           "CSS", "TCPA", "State Tax"]

        if file_extension.lower() == ".csv":
            contacts_df = pd.read_csv(contacts_path, usecols=contact_columns, dtype=str)
        elif file_extension.lower() in [".xls", ".xlsx"]:
            contacts_df = pd.read_excel(contacts_path, usecols=contact_columns, dtype=str)
        else:
            raise ValueError("Unsupported contacts file format. Please upload a CSV or Excel file.")

        contacts_df.fillna("", inplace=True)

        # Identify selected compliance categories based on 'Yes' values
        selected_categories = [col for col in contact_columns[4:] if "Yes" in contacts_df[col].values]

        # Read Compliance Excel
        df = pd.read_excel(excel_path, dtype=str, keep_default_na=False)
        df.columns = df.columns.astype(str)  # Ensure column names are strings

        # Rename "Return/Form/Payment" to "Compliance"
        if "Return/Form/Payment" in df.columns:
            df.rename(columns={"Return/Form/Payment": "Compliance"}, inplace=True)

        # Ensure "Due Date" is formatted correctly
        if "Due Date" in df.columns:
            df["Due Date"] = pd.to_datetime(df["Due Date"], errors="coerce").dt.strftime("%d-%m-%Y").fillna(df["Due Date"])

        # Sorting "Month" in correct month order (e.g., Jan-24 before Feb-24)
        if "Month" in df.columns:
            df["Month"] = pd.to_datetime(df["Month"], format="%b-%y", errors="coerce")  # Convert to datetime
            df = df.sort_values(by="Month")  # Sort in chronological order
            df["Month"] = df["Month"].dt.strftime("%b-%y")  # Convert back to original format

        # Filter compliance data based on selected categories
        df_filtered = df[df["Category"].isin(selected_categories)]

        session["compliance_data"] = df_filtered.to_dict(orient="records")
        session["contacts_data"] = contacts_df.to_dict(orient="records")
        session["excel_columns"] = list(df_filtered.columns)
        session["selected_compliance_categories"] = selected_categories  # Store selected categories

        return df_filtered.to_dict(orient="records"), contacts_df.to_dict(orient="records"), list(df_filtered.columns)

    except Exception as e:
        print(f"Error processing files: {e}")
        return [], [], []

def create_email_draft(service, to_email, recipient_name, entity_name, subject, compliance_data, table_month_year):
    """Creates an email draft with compliance details."""
    message = MIMEMultipart("related")
    message["to"] = to_email
    message["subject"] = f"Compliance Calendar - {table_month_year} < > {entity_name}"

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <div style="text-align: center;"><img src="cid:company_logo" width="200" height="52" alt="Company Logo" /></div>
        <h2 style="text-align: center; font-size: 22px; font-weight: bold; margin-top: -70px;">Compliances for {table_month_year}</h2>
        <div style="text-align: center;"><img src="cid:compliance_image" width="300" alt="Compliance Calendar" /></div>
        <p style="font-weight: bold; font-size: 18px; text-align: justify;">Dear {recipient_name},</p>
        <p style="font-weight: bold; font-size: 16px; text-align: left;">As the new month unfolds, businesses navigate the complexities of the tax and audit season, ensuring accurate and timely filing of Income Tax Returns (ITRs) and adherence to statutory audit guidelines.</p>
        <h3 style="text-align: center;">The compliances that are due in {table_month_year} are as follows:</h3>
        <table border="1" cellpadding="5" cellspacing="0" style="width: 100%; border-collapse: collapse; text-align: left;">
            <tr style="background-color: #f2f2f2;"><th>Compliance</th><th>Category</th><th>Due Date</th></tr>
    """

    for row in compliance_data:
        html_content += f"<tr><td>{row['Compliance']}</td><td>{row['Category']}</td><td>{row['Due Date']}</td></tr>"

    html_content += f"""
        </table>
        <br>
        <div style="text-align: center;"><p><strong>Want to be on top of compliances?</strong></p>
        <p><strong>Add our Compliance Calendar!</strong></p>
        <a href="{GOOGLE_CALENDAR_URL}" target="_blank" style="background: blue; color: white; padding: 10px 20px; border-radius: 20px; text-decoration: none;">Add calendar</a>
        <p><strong>We love feedback!</strong></p>
        <a href="{GOOGLE_FORM_URL}" target="_blank" style="background: blue; color: white; padding: 10px 20px; border-radius: 20px; text-decoration: none;">Feedback!</a>
        </div>
        <br>
        <p><strong>Thank you,</strong><br><strong>Team Zuna</strong></p>
        <p style="font-size: 12px;"><strong>Disclaimer: This is a general Zuna Compliance Calendar, not a list of everything we do for you. In accordance with the terms of your agreement with us, we will ensure that all compliances are met. Please contact your CSM if you would like us to take on the additional compliances.</strong></p>
        <p style="font-size: 12px;"><a href="https://www.zuna.one/" target="_blank">Visit our website</a></p>
    </body></html>
    """

    message.attach(MIMEText(html_content, "html"))

    with open(COMPANY_LOGO, "rb") as img:
        logo = MIMEImage(img.read())
        logo.add_header("Content-ID", "<company_logo>")  
        logo.add_header("Content-Disposition", "inline")
        message.attach(logo)

    with open(COMPLIANCE_IMAGE, "rb") as img:
        compliance_img = MIMEImage(img.read())
        compliance_img.add_header("Content-ID", "<compliance_image>") 
        compliance_img.add_header("Content-Disposition", "inline")
        message.attach(compliance_img)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = {"message": {"raw": raw_message}}
    service.users().drafts().create(userId="me", body=draft).execute()
    print(f"Draft email created for {to_email}")
