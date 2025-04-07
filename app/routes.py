from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import os
import pandas as pd
import shutil
from app.utils.helpers import process_files, create_email_draft, authenticate_gmail
from googleapiclient.discovery import build
from datetime import datetime

main_routes = Blueprint('main', __name__)

@main_routes.route('/', methods=['GET', 'POST'])
def index():
    excel_data = session.get("excel_data", [])
    excel_columns = session.get("excel_columns", [])
    contacts_data = session.get("contacts_data", [])
    contacts_columns = session.get("contacts_columns", [])

    filter_values = session.get("filter_values", {})
    unique_values = {}

    filter_columns = ["Month", "Category", "Country"]
    
    for column in filter_columns:
        if column in excel_columns:
            try:
                if column == "Month":
                    month_order = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                                   "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    
                    unique_values[column] = sorted(
                        set(str(row[column]) for row in excel_data if row[column]),
                        key=lambda x: month_order.get(x[:3], 0)  # Extract first 3 letters and sort
                    )
                else:
                    unique_values[column] = sorted(set(str(row[column]) for row in excel_data if row[column]))
            except ValueError as e:
                print(f"Error parsing {column}: {e}")
                unique_values[column] = sorted(set(str(row[column]) for row in excel_data if row[column]))  # Fallback
    
    if "Country" in contacts_columns:
        unique_values["Contacts_Country"] = sorted(set(str(row["Country"]) for row in contacts_data if row["Country"]))
    
    filter_type = request.form.get("filter_type", "")
    
    if filter_type == "compliance":
        selected_month = request.form.get("filter_Month_compliance", "").strip()
        selected_country = request.form.get("filter_Country_compliance", "").strip()
        
        filter_values["Month"] = selected_month
        filter_values["Country"] = selected_country
        
        filtered_data = [row for row in excel_data if 
                         (not selected_month or row.get("Month", "").strip() == selected_month) and
                         (not selected_country or row.get("Country", "").strip() == selected_country)]
        
        filtered_contacts = [row for row in contacts_data if 
                             not selected_country or row.get("Country", "").strip() == selected_country]
        
        session["filtered_excel_data"] = filtered_data
        session["filtered_contacts_data"] = filtered_contacts
        session["filter_values"] = filter_values
    
    elif filter_type == "contacts":
        selected_country = request.form.get("filter_Country_contacts", "").strip()
        filter_values["Contacts_Country"] = selected_country
        
        filtered_contacts = [row for row in contacts_data if 
                             not selected_country or row.get("Country", "").strip() == selected_country]
        session["filtered_contacts_data"] = filtered_contacts
    
    display_contacts_columns = [col for col in contacts_columns if col not in ["Category", "PAN"]]
    
    return render_template("index.html",
                           excel_data=session.get("filtered_excel_data", excel_data),
                           excel_columns=excel_columns,
                           contacts_data=session.get("filtered_contacts_data", contacts_data),
                           contacts_columns=display_contacts_columns,
                           filter_values=filter_values,
                           unique_values=unique_values)

@main_routes.route('/upload', methods=['POST'])
def upload_files():
    """Handles file uploads and processes the data."""
    if 'excel_file' not in request.files or 'contacts_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('main.index'))

    excel_file = request.files['excel_file']
    contacts_file = request.files['contacts_file']

    if excel_file.filename == '' or contacts_file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('main.index'))

    # Validate file extensions
    _, excel_ext = os.path.splitext(excel_file.filename)
    _, contacts_ext = os.path.splitext(contacts_file.filename)

    allowed_excel_ext = [".xls", ".xlsx"]
    allowed_contacts_ext = [".csv", ".xls", ".xlsx"]

    if excel_ext.lower() not in allowed_excel_ext:
        flash("Invalid file format. Please upload an Excel file (.xls, .xlsx) for compliance data.", "error")
        return redirect(url_for("main.index"))

    if contacts_ext.lower() not in allowed_contacts_ext:
        flash("Invalid file format. Please upload a CSV or Excel file (.csv, .xls, .xlsx) for contacts.", "error")
        return redirect(url_for("main.index"))

    # Ensure upload folder exists
    upload_folder = "app/static/uploads"
    os.makedirs(upload_folder, exist_ok=True)

    # Store filenames in session
    session["excel_filename"] = excel_file.filename
    session["contacts_filename"] = contacts_file.filename
    
    # Save files
    excel_path = os.path.join(upload_folder, excel_file.filename)
    contacts_path = os.path.join(upload_folder, contacts_file.filename)
    excel_file.save(excel_path)
    contacts_file.save(contacts_path)

    # Process uploaded files and store session data
    try:
        excel_data, contacts_data, excel_columns = process_files(excel_path, contacts_path)
        session["excel_data"] = excel_data
        session["contacts_data"] = contacts_data
        session["excel_columns"] = excel_columns
        session["contacts_columns"] = list(contacts_data[0].keys()) if contacts_data else []
        flash("Files uploaded successfully!", "success")
    except Exception as e:
        flash(f"Error processing files: {str(e)}", "error")
        return redirect(url_for('main.index'))

    print(f"? Stored {len(excel_data)} compliance records and {len(contacts_data)} contacts in session.")

    return redirect(url_for('main.index'))

@main_routes.route('/generate_email', methods=['POST'])
def generate_email():
    filtered_compliance_data = session.get("filtered_excel_data", [])
    filtered_contacts_data = session.get("filtered_contacts_data", [])
    
    if not filtered_compliance_data or not filtered_contacts_data:
        flash("No filtered compliance or contact data available to generate an email.", "error")
        return redirect(url_for('main.index'))
    
    try:
        service = authenticate_gmail()
        
        for contact in filtered_contacts_data:
            recipient_email = contact.get("email", "").strip() or contact.get("Email", "").strip()

            recipient_name = contact.get("Contact Person", "").strip()
            entity_name = contact.get("Entity Name", "").strip()
            
            if not recipient_email:
                continue
            
            entity_categories = [col for col, val in contact.items() if val.strip().lower() == 'yes']
            entity_compliance = [row for row in filtered_compliance_data if row.get("Category", "").strip() in entity_categories]
            
            if not entity_compliance:
                continue
            
            # Sort by Due Date (assumes format is YYYY-MM-DD or similar)
            entity_compliance.sort(key=lambda x: x.get("Due Date", ""))

            subject = f"Compliance Calendar - {datetime.now().strftime('%B %Y')} < > {entity_name}"
            create_email_draft(service, recipient_email, recipient_name, entity_name, subject, entity_compliance, datetime.now().strftime('%B %Y'))
        
        flash("Email drafts created successfully!", "success")
    except Exception as e:
        flash(f"Error generating email: {str(e)}", "error")
    
    return redirect(url_for('main.index'))
