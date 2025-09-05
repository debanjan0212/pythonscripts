import boto3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
from botocore.exceptions import ClientError, NoCredentialsError

# New imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import matplotlib.pyplot as plt

# --- Helper Functions (No changes) ---

def format_bytes(byte_count):
    if byte_count is None: return "0.0 B"
    power = 1024; n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while byte_count >= power and n < len(power_labels) - 1:
        byte_count /= power; n += 1
    return f"{byte_count:.2f} {power_labels[n]}"

# --- Data Fetching Functions (No changes) ---

def get_bucket_storage_info(cloudwatch_client, bucket_name):
    try:
        response = cloudwatch_client.get_metric_data(
            MetricDataQueries=[{'Id': 'total_size', 'MetricStat': {'Metric': {'Namespace': 'AWS/S3', 'MetricName': 'BucketSizeBytes', 'Dimensions': [{'Name': 'BucketName', 'Value': bucket_name}, {'Name': 'StorageType', 'Value': 'StandardStorage'}]}, 'Period': 86400, 'Stat': 'Average'}, 'ReturnData': True}],
            StartTime=datetime.now() - timedelta(days=3), EndTime=datetime.now(), ScanBy='TimestampDescending'
        )
        total_size_bytes = 0
        if response['MetricDataResults'][0]['Values']: total_size_bytes = response['MetricDataResults'][0]['Values'][0]
        return format_bytes(total_size_bytes)
    except ClientError as e:
        print(f"  - Warning: Could not get CloudWatch metrics for '{bucket_name}'. Reason: {e.response['Error']['Code']}")
        return "N/A"

def get_bucket_cost(costexplorer_client, bucket_name):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        response = costexplorer_client.get_cost_and_usage(
            TimePeriod={'Start': start_date.strftime('%Y-%m-%d'), 'End': end_date.strftime('%Y-%m-%d')},
            Granularity='MONTHLY', Metrics=['BlendedCost'],
            Filter={"And": [{"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Simple Storage Service"]}}, {"Dimensions": {"Key": "RESOURCE_ID", "Values": [bucket_name]}}]}
        )
        amount = response['ResultsByTime'][0]['Total']['BlendedCost']['Amount']
        return f"${float(amount):.2f}"
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ValidationException':
            print(f"  - Info: Cost Explorer ValidationException. Enable 'Resource and tag-level data' in AWS Billing preferences.")
        else: print(f"  - Warning: Could not get Cost Explorer data. Reason: {error_code}")
        return "N/A"

# --- Main Logic ---

def get_s3_insights():
    aws_profile = os.getenv('AWS_PROFILE', 'default')
    print(f"Using AWS Profile: '{aws_profile}'")
    try:
        session = boto3.Session(profile_name=aws_profile)
        s3_client, cloudwatch_client, costexplorer_client = (
            session.client('s3'), session.client('cloudwatch', region_name='us-east-1'), session.client('ce', region_name='us-east-1')
        )
        response = s3_client.list_buckets()
    except Exception as e:
        print(f"Error setting up AWS clients: {e}"); return

    buckets_data = []
    for bucket in response['Buckets']:
        bucket_name = bucket['Name']
        print(f"\nAnalyzing Bucket: {bucket_name}")
        try:
            print(f"  - Getting storage and cost info...")
            total_storage = get_bucket_storage_info(cloudwatch_client, bucket_name)
            estimated_cost = get_bucket_cost(costexplorer_client, bucket_name)
            
            location = s3_client.get_bucket_location(Bucket=bucket_name)['LocationConstraint'] or 'us-east-1'
            versioning_status = s3_client.get_bucket_versioning(Bucket=bucket_name).get('Status', 'Not Enabled')
            try:
                s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name); deletion_policy = "Enabled"
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchLifecycleConfiguration': deletion_policy = "Not Enabled"
                else: raise
            
            first_record_date, last_record_date, folder_structure, doc_types = analyze_objects(s3_client, bucket_name)
            is_working = "Yes" if last_record_date and (datetime.now(timezone.utc) - last_record_date).days < 30 else "No"
            
            buckets_data.append({
                'Account Profile': aws_profile, 'Bucket Name': bucket_name, 'Total Storage': total_storage,
                'Est. Cost (Last 30d)': estimated_cost, 'Creation Date': bucket['CreationDate'].strftime("%Y-%m-%d"),
                'Region': location, 'Versioning': versioning_status, 'Deletion Policy': deletion_policy,
                'Is Working Bucket': is_working
            })
        except Exception as e:
            print(f"An unexpected error occurred while analyzing bucket '{bucket_name}': {e}")

    if not buckets_data:
        print("\nNo buckets were found. Reports not generated."); return
    
    df = pd.DataFrame(buckets_data)
    
    # --- Generate Both Reports ---
    generate_excel_report(df, aws_profile)
    generate_pdf_report(df, aws_profile)

def analyze_objects(s3_client, bucket_name, sample_size=1000):
    paginator = s3_client.get_paginator('list_objects_v2'); pages = paginator.paginate(Bucket=bucket_name)
    first_record_date, last_record_date, folder_structure, doc_types, obj_count = None, None, set(), {}, 0
    try:
        for page in pages:
            if 'Contents' not in page: continue
            for obj in page['Contents']:
                obj_count += 1; mod_time = obj['LastModified']
                if first_record_date is None or mod_time < first_record_date: first_record_date = mod_time
                if last_record_date is None or mod_time > last_record_date: last_record_date = mod_time
                key = obj['Key']
                if '/' in key: folder_structure.add(key.split('/')[0])
                if '.' in os.path.basename(key):
                    doc_types[key.split('.')[-1].lower()] = doc_types.get(key.split('.')[-1].lower(), 0) + 1
                if obj_count >= sample_size: break
            if obj_count >= sample_size: break
    except ClientError as e:
        print(f"  - Warning: Could not list objects in '{bucket_name}'. Skipping object analysis. Error: {e.response['Error']['Code']}")
        return None, None, [], {}
    return first_record_date, last_record_date, list(folder_structure), doc_types

# --- REPORTING FUNCTIONS ---

def generate_excel_report(df, aws_profile):
    """Generates a multi-sheet Excel report with one sheet per region."""
    report_path = os.path.join('reports', f's3_bucket_report_{aws_profile}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    writer = pd.ExcelWriter(report_path, engine='xlsxwriter')
    
    # Summary Sheet
    print("\nCreating Excel summary sheet...")
    summary_df = df.groupby('Region')['Bucket Name'].count().reset_index().rename(columns={'Bucket Name': 'Bucket Count'})
    summary_df.to_excel(writer, sheet_name='Summary', index=False)
    
    # Region Sheets
    for region in sorted(df['Region'].unique()):
        print(f"Creating Excel sheet for region: {region}...")
        region_df = df[df['Region'] == region].copy()
        region_df.to_excel(writer, sheet_name=region, index=False)
    
    writer.close()
    print(f"✅ Excel report generated successfully: {report_path}")

def generate_pdf_report(df, aws_profile):
    """Generates a formatted PDF report with a summary and pages per region."""
    report_path = os.path.join('reports', f's3_bucket_report_{aws_profile}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf')
    doc = SimpleDocTemplate(report_path, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    story = []

    print("\nCreating PDF report...")
    
    # Title Page
    story.append(Paragraph("AWS S3 Bucket Analysis Report", styles['h1']))
    story.append(Paragraph(f"Account Profile: {aws_profile}", styles['h2']))
    story.append(Paragraph(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Spacer(1, 0.5 * inch))
    
    # Summary Table
    summary_df = df.groupby('Region')['Bucket Name'].count().reset_index().rename(columns={'Bucket Name': 'Bucket Count'})
    story.append(Paragraph("Account Summary by Region", styles['h2']))
    summary_data = [summary_df.columns.to_list()] + summary_df.values.tolist()
    summary_table = Table(summary_data)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black)
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.5 * inch))

    # Region-specific details
    for region in sorted(df['Region'].unique()):
        print(f"Creating PDF section for region: {region}...")
        region_df = df[df['Region'] == region].copy()
        
        story.append(Paragraph(f"Detailed Report for Region: {region}", styles['h2']))
        
        # Prepare data for the table (handling word wrap)
        region_df_display = region_df.drop(columns=['Account Profile', 'Region'])
        data = [region_df_display.columns.to_list()] + region_df_display.values.tolist()
        
        table = Table(data, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey), ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 12), ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5 * inch))

    doc.build(story)
    print(f"✅ PDF report generated successfully: {report_path}")

if __name__ == '__main__':
    get_s3_insights()
