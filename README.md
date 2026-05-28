
# 🛡️ AWS Automated EC2 Backup & Security Audit System

> Serverless AWS system that automatically backs up EC2 instances, audits security groups for dangerous open ports, and sends email alerts—runs every night at 2am with zero manual work.

![AWS](https://img.shields.io/badge/AWS-Cloud-orange?logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![Lambda](https://img.shields.io/badge/Serverless-Lambda-yellow?logo=aws-lambda)
![Status](https://img.shields.io/badge/Status-Live-brightgreen)
![Cost](https://img.shields.io/badge/Monthly%20Cost-%240.00-success)
![Region](https://img.shields.io/badge/Region-eu--north--1-informational)

---

## 📋 Table of Contents

- [The Problem](#the-problem)
- [Architecture](#architecture)
- [Services Used](#services-used)
- [Key Design Decisions](#key-design-decisions)
- [Security Audit](#security-audit)
- [How to Deploy](#how-to-deploy)
- [Test Results](#test-results)
- [Cost Breakdown](#cost-breakdown)
- [Challenges I Faced](#challenges-i-faced)
- [What I Learned](#what-i-learned)
- [Future Improvements](#future-improvements)

---

## 🔥 The Problem

In many AWS environments, backups and security checks are often handled manually. This can lead to missed backups or risky firewall rules remaining open for long periods.
Sometimes these issues are not noticed immediately, especially in small teams or learning environments.

This project solves both problems with a fully automated system

**Problem 1 — No automated backups**
Backups are forgotten, old snapshots pile up and cost money, or there is nothing to restore from when something breaks.

**Problem 2 — Security misconfigurations**
Someone opens SSH or a database port to the entire internet. Nobody notices. A hacker finds it first.

> The 2019 Capital One breach exposed 100 million customer records because of a single firewall misconfiguration. Thousands of MongoDB databases have been wiped because port 27017 was left open to the internet.

Both failures happen silently nobody knows until it is too late.

**This project solves both problems automatically.**

---

## 🏗️ Architecture

```
                    ┌─────────────────────┐
                    │   EventBridge       │
                    │   Scheduler         │
                    │   (2am UTC daily)   │
                    └──────────┬──────────┘
                               │ triggers
                               ▼
                    ┌─────────────────────┐
                    │                     │
                    │   Lambda Function   │◄── IAM Role
                    │   (Python 3.12)     │    (least-privilege)
                    │                     │
                    └──┬──────┬──────┬───┘
                       │      │      │
           ┌───────────┘      │      └────────────┐
           │                  │                   │
           ▼                  ▼                   ▼
  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐
  │  EC2 + EBS     │  │  Security    │  │   S3 Bucket    │
  │                │  │  Groups      │  │                │
  │ • Find tagged  │  │              │  │ • debug.json   │
  │   instances    │  │ • Scan all   │  │ • errors.json  │
  │ • Snapshot     │  │   groups     │  │                │
  │   volumes      │  │ • Flag open  │  │ (audit trail)  │
  │ • Delete old   │  │   ports      │  │                │
  │   snapshots    │  │              │  │                │
  └────────────────┘  └──────────────┘  └────────────────┘
           │                  │
           └────────┬─────────┘
                    │
                    ▼
           ┌────────────────┐
           │   SNS Topic    │
           │                │
           │ • Email report │
           │ • Risk alerts  │
           │ • Run summary  │
           └────────────────┘
                    │
                    ▼
            Your Email Inbox
```

### How the flow works step by step

```
Every night at 2am UTC
        │
        ▼
EventBridge wakes up Lambda
        │
        ▼
Step 1 → Find all EC2 instances tagged backup=true
        │
        ▼
Step 2 → Snapshot every EBS volume on those instances
        │
        ▼
Step 3 → Delete snapshots older than 7 days (cost control)
        │
        ▼
Step 4 → Scan every security group for dangerous open ports
        │
        ▼
Step 5 → Save debug log + error log to S3
        │
        ▼
Step 6 → Send email report via SNS
        │
        ▼
Lambda goes back to sleep — cost: $0.00
        │
        ▼
Repeats tomorrow automatically
```

---

## ⚙️ Services Used

| Service | What it does in this project | Why this service |
|---|---|---|
| **EC2** | The server being backed up and audited | Industry standard VM — most companies use EC2 for servers |
| **EBS Snapshots** | Point-in-time disk backup copies | Incremental — only changed blocks stored, very cost-efficient |
| **Lambda** | Runs all automation logic serverlessly | Zero cost when idle, no server to manage or patch |
| **IAM** | Controls what Lambda is allowed to do | Least-privilege — Lambda gets only the 6 permissions it needs |
| **S3** | Stores debug logs and audit reports | 99.999999999% durable, permanent audit trail, cheap long-term |
| **Security Groups** | Virtual firewalls scanned for misconfigurations | Most common source of AWS security breaches |
| **SNS** | Sends email alert after every run | Decoupled notifications — add Slack or SMS without code changes |
| **EventBridge** | Triggers Lambda at 2am every day | Modern AWS scheduler with built-in retry logic |
| **boto3** | Python SDK — connects code to AWS services | Official SDK, uses IAM role auth — no hardcoded credentials |

---

## 🎯 Key Design Decisions

### Decision 1 — Tag-based targeting instead of hardcoded IDs

```python
# Lambda finds instances by tag — not by hardcoded ID
ec2.describe_instances(
    Filters=[{'Name': 'tag:backup', 'Values': ['true']}]
)
```

**Why:** If I hardcode instance IDs, they break the moment a server is replaced — the ID changes. With tags, any team can opt their instance into backup by adding one tag. No code change needed. Scales to hundreds of instances automatically.

---

### Decision 2 — Least-privilege IAM with 3 separate policies

```
ec2-backup-snapshot-policy  → only: CreateSnapshot, DescribeInstances, DeleteSnapshot
ec2-security-audit-policy   → only: DescribeSecurityGroups, S3:PutObject
sns-publish-policy          → only: sns:Publish to ONE specific topic ARN
```

**Why:** If this Lambda were ever compromised, an attacker could only create snapshots and send one SNS message. They cannot delete EC2 instances, access databases, or touch anything else. This is how production systems are secured.

---

### Decision 3 — Safe automatic cleanup

```python
# Only deletes snapshots this Lambda created — never touches manually created ones
old_snaps = ec2.describe_snapshots(
    Filters=[
        {'Name': 'tag:CreatedBy', 'Values': ['ec2-backup-lambda']},
        {'Name': 'status', 'Values': ['completed']}
    ],
    OwnerIds=['self']
)
cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)
```

**Why:** Without cleanup, snapshots accumulate forever at $0.05/GB/month. The `CreatedBy` tag ensures cleanup never touches snapshots created by other tools or manually.

---

### Decision 4 — Independent error handling per phase

```python
# If backup fails, audit still runs
# If audit fails, logs still save
# If logs fail, email still sends
try:
    snapshot = ec2.create_snapshot(...)
except Exception as e:
    logger.error('BACKUP', f"Failed {volume_id}", exception=e)
    # continues to next volume — does not crash
```

**Why:** Without this, one failed volume stops all other instances from being backed up. Each phase is independent — partial failure does not cause total failure.

---

### Decision 5 — Dual log files per run

Every run saves two files to S3:
```
logs/2025-05-27-0200-debug.json   ← every step logged with timestamp
logs/2025-05-27-0200-errors.json  ← errors only, empty = clean run
```

**Why:** CloudWatch logs expire after 90 days. S3 stores forever. If something fails at 2am you download the debug file and see exactly which step failed — without being awake when it happens.

---

## 🔒 Security Audit

The Lambda scans every security group and flags inbound rules allowing these ports from `0.0.0.0/0` (the entire internet):

| Port | Service | Why It Is Dangerous |
|---|---|---|
| **22** | SSH | Remote server login accessible to entire internet |
| **3389** | RDP | Windows remote desktop accessible to entire internet |
| **3306** | MySQL | Database readable by anyone on internet |
| **5432** | PostgreSQL | Database readable by anyone on internet |
| **27017** | MongoDB | Database readable by anyone on internet |
| **6379** | Redis | Cache readable by anyone on internet |
| **9200** | Elasticsearch | Search index readable by anyone on internet |
| **23** | Telnet | Unencrypted remote access from entire internet |

> **Real impact:** The 2019 Capital One hack (100M records exposed) started with a single misconfigured firewall rule. All these ports should only ever allow specific trusted IP ranges — never 0.0.0.0/0.

---

## 🚀 How to Deploy

### Prerequisites
- AWS account with CLI configured (`aws configure`)
- IAM user with EC2, Lambda, S3, SNS, IAM, EventBridge permissions

### Step 1 — Create S3 bucket for logs
```bash
aws s3 mb s3://ec2-backup-logs-yourname \
  --region eu-north-1
```

### Step 2 — Create IAM Role
```
IAM → Roles → Create Role → AWS Service → Lambda
Name: ec2-backup-lambda-role
```
Attach the 3 JSON policies from the `/iam-policies/` folder in this repo.

### Step 3 — Create SNS Topic
```
SNS → Topics → Create topic → Standard
Name: ec2-backup-alerts
```
Subscribe email and click the confirmation link AWS sends.

### Step 4 — Deploy Lambda
```
Lambda → Create function → Author from scratch
Name:    ec2-backup-function
Runtime: Python 3.12
Role:    ec2-backup-lambda-role
Timeout: 1 minute (Configuration → General)
```

Update these 3 lines at the top of `lambda_function.py`:
```python
REGION        = 'eu-north-1'
S3_BUCKET     = 'ec2-backup-logs-yourname'
SNS_TOPIC_ARN = 'arn:aws:sns:eu-north-1:YOUR_ACCOUNT_ID:ec2-backup-alerts'
```

### Step 5 — Tag EC2 instances
```
EC2 → Instances → your instance → Tags → Manage tags
Key: backup    Value: true
```
⚠️ Value must be lowercase `true` — the Lambda filters exactly for this value.

### Step 6 — Create EventBridge schedule
```
EventBridge → Schedules → Create schedule
Name:       ec2-daily-backup-schedule
Cron:       0 2 * * ? *
Target:     Lambda → ec2-backup-function
Retries:    3
```

### Step 7 — Test
```
Lambda → ec2-backup-function → Test tab → {} → Run
```

Expected output:
```json
{
  "status": "success",
  "results": {
    "summary": "Snapshots created: 1 | Security risks: 2 | Errors: 0",
    "debug_log": "s3://ec2-backup-logs-yourname/logs/2025-05-27-0200-debug.json"
  }
}
```

---

## ✅ Test Results

| What was tested | Result | How verified |
|---|---|---|
| EC2 snapshot created | ✅ Pass | EC2 → Snapshots console — snapshot visible |
| Snapshot tagged with metadata | ✅ Pass | Tags: CreatedBy, RetainUntil, InstanceId all present |
| Old snapshot cleanup | ✅ Pass | Snapshots older than 7 days automatically deleted |
| Security group audit | ✅ Pass | Detected 2 open port risks in test environment |
| Debug log saved to S3 | ✅ Pass | logs/TIMESTAMP-debug.json created in S3 |
| Error log saved to S3 | ✅ Pass | logs/TIMESTAMP-errors.json created in S3 |
| SNS email received | ✅ Pass | Report delivered to inbox within 60 seconds |
| EventBridge schedule | ✅ Pass | Status: Enabled, next run at 2:00 AM UTC |
| IAM least-privilege | ✅ Pass | AuthorizationError confirmed on non-permitted actions |

---

## 💰 Cost Breakdown

This project runs at **$0.00/month** within AWS Free Tier:

| Service | Free Tier Limit | This Project Uses | Monthly Cost |
|---|---|---|---|
| Lambda | 1M requests free | ~30 requests | $0.00 |
| EventBridge | 14M events free | ~30 events | $0.00 |
| SNS | 1M publishes free | ~30 publishes | $0.00 |
| S3 | 5GB free | ~1MB logs | $0.00 |
| EBS Snapshots | Not free | 20GB × 7 days | ~$0.07 |

> **Total: ~$0.07/month.** The 7-day auto-cleanup prevents snapshot costs from growing over time.

---

## 🐛 Challenges I Faced

These are real issues I debugged during the build — not theoretical:

| Challenge | What happened | How I fixed it |
|---|---|---|
| Region mismatch | Lambda queried us-east-1 but EC2 was in eu-north-1 — snapshots_created was always empty | Read CloudWatch logs step by step, found the BACKUP step showed 0 instances, traced it to the REGION variable |
| IAM AuthorizationError on SNS | Lambda crashed with `not authorized to perform SNS:Publish` | Discovered the account ID in the IAM policy (440156018213) did not match actual account (607081650044) — copied ARN directly from SNS console |
| Syntax error on line 14 | Lambda crashed immediately with `invalid syntax` | ARN was pasted without quotes — Python needs single quotes around any text value |
| SNS subscription pending | Lambda sent messages but no email arrived | Confirmation email went to spam — clicked confirm, status changed from PendingConfirmation to Confirmed |
| EC2 tag case sensitive | Snapshots not created even after tagging | Value was `True` with capital T — Lambda filters exactly for lowercase `true` |

> **Key lesson:** Every one of these errors was found by reading CloudWatch logs carefully. Good logging is not optional — it is how you debug production systems.

---

## 📚 What I Learned

**Technical skills:**
- How Lambda, EventBridge, SNS, S3, EC2, IAM work together in a real system
- IAM least-privilege design — why it matters and how to implement it
- EBS snapshot lifecycle — creating, tagging, and cleaning up automatically
- Security group auditing — what makes a port dangerous and why
- boto3 — how Python talks to AWS services without hardcoded credentials
- Structured logging — saving debug and error logs separately for easy troubleshooting
- Python error handling — try/except patterns for resilient automation

**Problem-solving skills:**
- Debugging AWS permission errors by reading exact error messages
- Tracing region mismatches through CloudWatch logs
- Understanding why copying ARNs directly beats typing them manually

---

## 🔮 Future Improvements

| Improvement | Why it would help |
|---|---|
| Terraform for all infrastructure | Deploy entire project in one command on any AWS account |
| Environment variables for RETAIN_DAYS | Dev keeps 3 days, prod keeps 30 — no code changes needed |
| Slack webhook on SNS topic | Team gets alerts in Slack without changing Lambda code |
| Cross-account IAM roles | Back up EC2 across multiple AWS accounts from one Lambda |
| Step Functions workflow | Visual monitoring of each backup step, better retry control |
| CloudWatch dashboard | Real-time metrics — backup success rate, risks over time |
| SNS message filtering | Dev team gets dev alerts only, prod team gets prod alerts only |

---

## 📁 Repository Structure

```
aws-ec2-backup-security-audit/
│
├── README.md                              ← project documentation
├── lambda_function.py                     ← main Lambda code
├── iam-policies/
│   ├── ec2-backup-snapshot-policy.json   ← EC2 + CloudWatch permissions
│   ├── ec2-security-audit-policy.json    ← Security group + S3 permissions
│   └── sns-publish-policy.json           ← SNS publish permission
└── screenshots/
    ├── ec2-snapshots.png                 ← proof of snapshots created
    ├── email-alert.png                   ← proof of SNS email received
    ├── eventbridge-schedule.png          ← schedule enabled
    ├── s3-logs.png                       ← debug logs in S3
    └── iam-policies.png                  ← 3 policies on Lambda role
```

---

## 🛠️ Common Errors and Fixes

| Error message | Cause | Fix |
|---|---|---|
| `snapshots_created: []` | EC2 missing `backup=true` tag or wrong case | Add tag Key=backup Value=true (lowercase) |
| `AuthorizationError SNS:Publish` | Wrong account ID in IAM policy | Copy ARN directly from SNS → Topics console |
| `Topic does not exist` | ARN typo in Lambda code | Copy SNS topic ARN from console, paste with quotes |
| `Syntax error line 14` | Missing quotes around ARN string | Wrap ARN in single quotes: `'arn:aws:sns:...'` |
| `No instances found` | Lambda region ≠ EC2 region | Update REGION variable to match your EC2 region |
| `PendingConfirmation` | Email subscription not confirmed | Check spam folder, click confirm link in AWS email |

---

*Built as part of a cloud infrastructure learning journey. Deployed and tested live on AWS eu-north-1 (Stockholm, Sweden).*

*Demonstrates: serverless architecture, IAM least-privilege, security auditing, operational logging, cost-aware design.*
