import boto3
import json
from datetime import datetime, timezone, timedelta

# ============================================================
# CONFIGURATION — update these 3 lines only
# ============================================================
REGION        = 'eu-north-1'
S3_BUCKET     = 'ec2-backup-logs-kk'
SNS_TOPIC_ARN = 'arn:aws:sns:eu-north-1:607081650044:ec2-backup-alert'
RETAIN_DAYS   = 7

DANGEROUS_PORTS = {
    22:    "SSH — remote server access",
    3389:  "RDP — Windows remote desktop",
    3306:  "MySQL database",
    5432:  "PostgreSQL database",
    27017: "MongoDB database",
    6379:  "Redis cache",
    9200:  "Elasticsearch",
    23:    "Telnet — unencrypted remote access"
}

# ============================================================
# LOGGER — saves every step to S3
# ============================================================
class DebugLogger:
    def __init__(self, timestamp):
        self.timestamp = timestamp
        self.logs      = []
        self.errors    = []

    def log(self, step, message, data=None):
        entry = {
            'time':    datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'step':    step,
            'message': message,
        }
        if data:
            entry['data'] = data
        self.logs.append(entry)
        print(f"[{entry['time']}] {step}: {message}")

    def error(self, step, message, exception=None):
        entry = {
            'time':      datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'step':      step,
            'message':   message,
            'exception': str(exception) if exception else None
        }
        self.errors.append(entry)
        self.logs.append({**entry, 'level': 'ERROR'})
        print(f"[ERROR] {step}: {message} | {exception}")

    def save_to_s3(self, s3_client):
        debug_key = f"logs/{self.timestamp}-debug.json"
        s3_client.put_object(
            Bucket      = S3_BUCKET,
            Key         = debug_key,
            Body        = json.dumps({
                'run_timestamp': self.timestamp,
                'total_steps':   len(self.logs),
                'error_count':   len(self.errors),
                'logs':          self.logs
            }, indent=2),
            ContentType = 'application/json'
        )
        error_key = f"logs/{self.timestamp}-errors.json"
        s3_client.put_object(
            Bucket      = S3_BUCKET,
            Key         = error_key,
            Body        = json.dumps({
                'run_timestamp': self.timestamp,
                'error_count':   len(self.errors),
                'errors':        self.errors
            }, indent=2),
            ContentType = 'application/json'
        )
        print(f"Debug log: s3://{S3_BUCKET}/{debug_key}")
        print(f"Error log: s3://{S3_BUCKET}/{error_key}")
        return debug_key, error_key


# ============================================================
# MAIN HANDLER
# ============================================================
def lambda_handler(event, context):
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')
    logger    = DebugLogger(timestamp)
    ec2       = boto3.client('ec2', region_name=REGION)
    s3        = boto3.client('s3',  region_name=REGION)

    results = {
        'timestamp':         timestamp,
        'region':            REGION,
        'snapshots_created': [],
        'snapshots_deleted': [],
        'security_risks':    [],
        'clean_groups':      [],
        'errors':            []
    }

    logger.log('START', f"Lambda started — region: {REGION}")

    # --------------------------------------------------------
    # PART 1 — EC2 BACKUP
    # --------------------------------------------------------
    logger.log('BACKUP', "Searching for EC2 instances tagged backup=true")
    try:
        response  = ec2.describe_instances(
            Filters=[{'Name': 'tag:backup', 'Values': ['true']}]
        )
        instances = [
            inst
            for r in response['Reservations']
            for inst in r['Instances']
        ]
        logger.log(
            'BACKUP',
            f"Found {len(instances)} instance(s) to back up",
            data={'instance_ids': [i['InstanceId'] for i in instances]}
        )
    except Exception as e:
        logger.error('BACKUP', "Failed to describe instances", exception=e)
        instances = []
        results['errors'].append(str(e))

    for instance in instances:
        instance_id   = instance['InstanceId']
        instance_name = next(
            (t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'),
            'unnamed'
        )
        instance_state = instance['State']['Name']

        logger.log(
            'BACKUP',
            f"Processing {instance_name} ({instance_id}) — state: {instance_state}"
        )

        for mapping in instance.get('BlockDeviceMappings', []):
            volume_id   = mapping['Ebs']['VolumeId']
            device_name = mapping['DeviceName']

            logger.log('BACKUP', f"Snapshotting volume {volume_id} ({device_name})")

            try:
                snapshot = ec2.create_snapshot(
                    VolumeId    = volume_id,
                    Description = f"Auto backup - {instance_name} - {timestamp}",
                    TagSpecifications=[{
                        'ResourceType': 'snapshot',
                        'Tags': [
                            {'Key': 'Name',
                             'Value': f"backup-{instance_name}-{timestamp}"},
                            {'Key': 'InstanceId',
                             'Value': instance_id},
                            {'Key': 'Device',
                             'Value': device_name},
                            {'Key': 'CreatedBy',
                             'Value': 'ec2-backup-lambda'},
                            {'Key': 'RetainUntil',
                             'Value': (
                                 datetime.now(timezone.utc)
                                 + timedelta(days=RETAIN_DAYS)
                             ).strftime('%Y-%m-%d')}
                        ]
                    }]
                )
                snap_id = snapshot['SnapshotId']
                logger.log('BACKUP', f"Snapshot created: {snap_id}")
                results['snapshots_created'].append({
                    'instance_id':     instance_id,
                    'instance_name':   instance_name,
                    'volume_id':       volume_id,
                    'snapshot_id':     snap_id,
                    'device':          device_name,
                    'state_at_backup': instance_state
                })

            except Exception as e:
                logger.error(
                    'BACKUP',
                    f"Failed to snapshot {volume_id}",
                    exception=e
                )
                results['errors'].append(str(e))

    # --------------------------------------------------------
    # PART 2 — CLEANUP OLD SNAPSHOTS
    # --------------------------------------------------------
    logger.log('CLEANUP', f"Checking for snapshots older than {RETAIN_DAYS} days")
    try:
        old_snaps = ec2.describe_snapshots(
            Filters=[
                {'Name': 'tag:CreatedBy', 'Values': ['ec2-backup-lambda']},
                {'Name': 'status',        'Values': ['completed']}
            ],
            OwnerIds=['self']
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)

        for snap in old_snaps['Snapshots']:
            if snap['StartTime'] < cutoff:
                ec2.delete_snapshot(SnapshotId=snap['SnapshotId'])
                logger.log('CLEANUP', f"Deleted old snapshot {snap['SnapshotId']}")
                results['snapshots_deleted'].append(snap['SnapshotId'])

        logger.log(
            'CLEANUP',
            f"Cleanup done — deleted {len(results['snapshots_deleted'])} snapshot(s)"
        )

    except Exception as e:
        logger.error('CLEANUP', "Cleanup failed", exception=e)
        results['errors'].append(str(e))

    # --------------------------------------------------------
    # PART 3 — SECURITY AUDIT
    # --------------------------------------------------------
    logger.log('AUDIT', "Starting security group audit")
    try:
        sgs = ec2.describe_security_groups()['SecurityGroups']
        logger.log('AUDIT', f"Auditing {len(sgs)} security group(s)")

        for sg in sgs:
            sg_id   = sg['GroupId']
            sg_name = sg['GroupName']
            risks   = []

            for rule in sg.get('IpPermissions', []):
                from_port = rule.get('FromPort', 0)
                to_port   = rule.get('ToPort',   0)
                protocol  = rule.get('IpProtocol', '')

                if protocol == '-1':
                    for ip in rule.get('IpRanges', []):
                        if ip['CidrIp'] == '0.0.0.0/0':
                            risks.append({
                                'type':        'ALL_TRAFFIC_OPEN',
                                'severity':    'CRITICAL',
                                'description': 'All ports and protocols open to internet'
                            })

                for ip in rule.get('IpRanges', []):
                    if ip['CidrIp'] == '0.0.0.0/0':
                        for port, desc in DANGEROUS_PORTS.items():
                            if from_port <= port <= to_port:
                                risks.append({
                                    'type':        'DANGEROUS_PORT_OPEN',
                                    'severity':    'HIGH',
                                    'port':        port,
                                    'description': desc
                                })

            if risks:
                logger.log(
                    'AUDIT',
                    f"RISK: {sg_name} ({sg_id}) — {len(risks)} risk(s) found",
                    data={'risks': risks}
                )
                results['security_risks'].append({
                    'sg_id':   sg_id,
                    'sg_name': sg_name,
                    'risks':   risks
                })
            else:
                logger.log('AUDIT', f"CLEAN: {sg_name} ({sg_id})")
                results['clean_groups'].append(sg_id)

    except Exception as e:
        logger.error('AUDIT', "Security audit failed", exception=e)
        results['errors'].append(str(e))

    # --------------------------------------------------------
    # PART 4 — SAVE DEBUG LOGS TO S3
    # --------------------------------------------------------
    logger.log('SAVE', "Saving debug logs to S3")
    try:
        debug_key, error_key = logger.save_to_s3(s3)
        results['debug_log'] = f"s3://{S3_BUCKET}/{debug_key}"
        results['error_log'] = f"s3://{S3_BUCKET}/{error_key}"
    except Exception as e:
        logger.error('SAVE', "Could not save logs to S3", exception=e)
        results['errors'].append(str(e))

    # --------------------------------------------------------
    # PART 5 — SEND EMAIL ALERT VIA SNS
    # --------------------------------------------------------
    logger.log('ALERT', "Sending SNS email alert")
    try:
        sns_client = boto3.client('sns', region_name=REGION)

        # Build snapshot summary
        if results['snapshots_created']:
            snap_lines = "SNAPSHOTS CREATED:\n"
            for s in results['snapshots_created']:
                snap_lines += (
                    f"  {s['instance_name']} "
                    f"({s['instance_id']}) "
                    f"-> {s['snapshot_id']}\n"
                )
        else:
            snap_lines = "SNAPSHOTS: None created — check backup=true tag on EC2\n"

        # Build security risk summary
        if results['security_risks']:
            risk_lines = f"SECURITY RISKS FOUND ({len(results['security_risks'])}):\n"
            for r in results['security_risks']:
                risk_lines += f"  {r['sg_name']} ({r['sg_id']})\n"
                for risk in r['risks']:
                    risk_lines += (
                        f"    - {risk['description']} "
                        f"[{risk['severity']}]\n"
                    )
        else:
            risk_lines = "SECURITY: All security groups clean. No dangerous ports found.\n"

        # Build error summary
        if results['errors']:
            error_lines = f"ERRORS ({len(results['errors'])}):\n"
            for e in results['errors']:
                error_lines += f"  - {e}\n"
        else:
            error_lines = "ERRORS: None\n"

        # Full email body
        message = (
            f"AWS Backup and Security Audit Report\n"
            f"=====================================\n"
            f"Time:    {timestamp} UTC\n"
            f"Region:  {REGION}\n"
            f"Account: 607081650044\n\n"
            f"{snap_lines}\n"
            f"{risk_lines}\n"
            f"{error_lines}\n"
            f"Debug log: {results.get('debug_log', 'not saved')}\n"
            f"Error log: {results.get('error_log', 'not saved')}\n"
            f"=====================================\n"
            f"Automated by ec2-backup-lambda\n"
            f"Runs daily at 2am UTC\n"
        )

        # Subject changes based on outcome
        if results['security_risks'] or results['errors']:
            subject = (
                f"WARNING — AWS Backup: "
                f"{len(results['snapshots_created'])} snapshots, "
                f"{len(results['security_risks'])} security risks found"
            )
        else:
            subject = (
                f"OK — AWS Backup: "
                f"{len(results['snapshots_created'])} snapshots created, "
                f"all security groups clean"
            )

        sns_client.publish(
            TopicArn = SNS_TOPIC_ARN,
            Subject  = subject,
            Message  = message
        )
        logger.log('ALERT', "Email alert sent successfully")

    except Exception as e:
        logger.error('ALERT', "SNS alert failed", exception=e)
        results['errors'].append(f"SNS failed: {str(e)}")

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------
    summary = (
        f"Snapshots created: {len(results['snapshots_created'])} | "
        f"Security risks:    {len(results['security_risks'])} | "
        f"Errors:            {len(results['errors'])}"
    )
    logger.log('DONE', summary)
    results['summary'] = summary

    print("\n===== FINAL SUMMARY =====")
    print(summary)
    print(json.dumps(results, indent=2, default=str))

    return {'status': 'success', 'results': results}
