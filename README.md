# AWS-Automated-Ec2-backup-Security-Audit-system
Serverless AWS system that automates EC2 backups, audits security groups  for dangerous open ports, and sends email alerts, 8 services, zero cost.
AWS Automated EC2 Backup & Security Audit System

This project automates EC2 backups and basic security auditing in AWS using a serverless approach.

While learning AWS cloud infrastructure, I noticed that backup management and security group monitoring are repetitive tasks that are easy to forget when handled manually. To solve this, I built a Lambda-based automation system that runs every night and performs backup, cleanup, security checks, logging, and email notifications automatically.

The system is fully event-driven and does not require any server management.

#What This Project Does:

Finds EC2 instances tagged with backup=true
Creates EBS snapshots automatically
Deletes old snapshots after 7 days to reduce storage cost
Scans security groups for risky open ports
Stores debug and error logs in S3
Sends an email report using SNS
Runs automatically every day at 2 AM using EventBridge

#Architecture:

EventBridge Schedule (2 AM daily)
            │
            ▼
      AWS Lambda Function
            │
 ┌──────────┼──────────┐
 │          │          │
 ▼          ▼          ▼
EC2      Security      S3
Backup    Audit       Logs
 │          │
 ▼          ▼
EBS       SNS Email
Snapshots  Alerts



| Service         | Usage                        |
| --------------- | ---------------------------- |
| EC2             | Instances being backed up    |
| EBS Snapshots   | Disk-level backup storage    |
| Lambda          | Main automation logic        |
| IAM             | Secure permission management |
| S3              | Debug and audit log storage  |
| SNS             | Email notifications          |
| EventBridge     | Daily scheduling             |
| Security Groups | Firewall auditing            |
| boto3           | Python SDK for AWS           |




##Why I Built This:
In many AWS environments, backups and security checks are often handled manually. Sometimes:
backups are forgotten
old snapshots keep increasing storage cost
risky ports like SSH or database ports remain publicly open

##I wanted to create a small automation project that could reduce manual work and improve visibility using AWS serverless services.

##This project also helped me understand:

Lambda automation
IAM least privilege access
AWS event-driven architecture
security group auditing
logging and monitoring concepts



#Key Features:
Automated EC2 Backup
The Lambda function checks for EC2 instances with this tag:
Filters=[{'Name': 'tag:backup', 'Values': ['true']}]
This makes the system flexible because new instances can be added without changing the code.


#Snapshot Cleanup:

Old snapshots older than 7 days are deleted automatically.
This prevents unnecessary storage cost accumulation.
cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)

#Security Group Audit:
##The project checks security groups for dangerous ports open to the internet (0.0.0.0/0).

#Ports monitored:

22 → SSH
3389 → RDP
3306 → MySQL
5432 → PostgreSQL
27017 → MongoDB
6379 → Redis
9200 → Elasticsearch
23 → Telnet

##If risky ports are detected, the system sends an SNS email alert.


#Logging

Each Lambda execution stores:
debug logs
error logs
inside an S3 bucket for troubleshooting and auditing.
logs/TIMESTAMP-debug.json
logs/TIMESTAMP-errors.json


#Security Approach:

I used IAM least-privilege access while creating the Lambda role.
The Lambda only has permissions required for:
creating snapshots
reading EC2/security group information
uploading logs to S3
publishing SNS notifications
This reduces unnecessary access to other AWS resources.


#Deployment Steps:

1. Create S3 Bucket
aws s3 mb s3://ec2-backup-logs-kk \
  --region eu-north-1

2. Create IAM Role for Lambda
Create a Lambda IAM role and attach:
EC2 snapshot permissions
security group read permissions
SNS publish permissions
S3 upload permissions

3. Create SNS Topic
SNS → Topics → Create Topic
Subscribe email to receive alerts.

4. Deploy Lambda Function
Create a Python 3.12 Lambda function and paste the project code.
Update these variables:
REGION        = 'eu-north-1'
S3_BUCKET     = 'your-bucket-name'
SNS_TOPIC_ARN = 'your-sns-topic-arn'

5. Tag EC2 Instances
Add this tag:
Key: backup
Value: true

6. Create EventBridge Schedule
Schedule the Lambda to run daily at 2 AM.


#Challenges I Faced:

Initially faced IAM permission issues while publishing SNS alerts
Lambda could not detect EC2 instances because the region was mismatched
Some security group rules required additional validation logic
Testing EventBridge scheduling took time because of cron configuration mistakes

#These issues helped me better understand AWS troubleshooting and IAM debugging.

#What I Learned:

AWS Lambda automation
Working with EBS snapshots
IAM least privilege design
Security group auditing
Using SNS for notifications
Storing logs in S3
EventBridge scheduling
Python error handling using try/except
Basic operational monitoring concepts

#Future Improvements:

Some improvements I would like to add later:
Slack alert integration
Multi-account backup support
Step Functions workflow
Environment variables for configuration
CloudWatch dashboard monitoring

#Cost:

The project mainly stays within AWS Free Tier usage.
Only EBS snapshots may create small storage charges depending on disk size. Automatic cleanup helps reduce long-term cost.

#Final Note:

This project was built as part of my cloud and security learning journey. It helped me understand how different AWS services work together in a real-world automation workflow using serverless architecture.
Deployed and tested in AWS eu-north-1 (Stockholm).
  
