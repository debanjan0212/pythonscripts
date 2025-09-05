# AWS S3 Bucket Analyzer & Reporter

This script provides a comprehensive analysis of all S3 buckets in an AWS account. It gathers insights on usage, storage, cost, and configuration, then generates detailed reports in both Excel (`.xlsx`) and PDF (`.pdf`) formats.

## Features

-   Lists all S3 buckets in the specified AWS account.
-   Retrieves key metadata: Creation Date, Region, Versioning, and Deletion Policies.
-   Calculates total storage utilization using Amazon CloudWatch.
-   Estimates the monthly cost of each bucket using AWS Cost Explorer.
-   Analyzes a sample of objects to determine:
    -   First and last modified dates.
    -   Top-level folder structures.
    -   A summary of stored document types.
-   Generates multi-sheet Excel reports, with a dedicated tab for each region.
-   Generates a formatted PDF report with a summary and region-specific pages.

## Prerequisites

-   Python 3.8+
-   An AWS account with credentials configured via the AWS CLI.
-   Required IAM permissions for the user/role running the script:
    -   `s3:ListAllMyBuckets`, `s3:GetBucket*`, `s3:ListBucket`
    -   `cloudwatch:GetMetricData`, `cloudwatch:ListMetrics`
    -   `ce:GetCostAndUsage`

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd aws-s3-reporter
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure AWS Cost Explorer:**
    For the cost reporting feature to work, you must enable "Resource and tag-level data" in the AWS Billing console. This can take up to 24 hours to take effect.

## How to Run

The script uses the AWS profile set in your environment.

1.  **For the default AWS profile:**
    ```bash
    python s3_analyzer.py
    ```

2.  **For a specific named profile (e.g., 'production'):**
    ```bash
    export AWS_PROFILE=production
    python s3_analyzer.py
    ```

The generated reports will be saved in the `reports/` directory.
