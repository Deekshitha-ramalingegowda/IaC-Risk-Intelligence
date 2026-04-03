#!/usr/bin/env python3

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime

try:
    from google import genai
except ImportError:
    print("google-genai is not installed. Run: pip install google-genai")
    sys.exit(1)


MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-pro",
]


# ============================================================================
# FILE LOADING
# ============================================================================

def load_json_file(filename):
    for encoding in ["utf-8-sig", "utf-16", "utf-16-le", "utf-8", "latin-1"]:
        try:
            with open(filename, "r", encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    print(f"Error: Could not parse {filename}")
    return None


def load_terraform_sources(terraform_dir="terraform"):
    for search_dir in [terraform_dir, "."]:
        base = Path(search_dir)
        if not base.is_dir():
            continue
        tf_files = sorted(base.rglob("*.tf"))
        if not tf_files:
            continue
        parts = []
        for tf_path in tf_files:
            try:
                content = tf_path.read_text(encoding="utf-8", errors="replace")
                numbered = "\n".join(
                    f"{i+1:4d}  {line}"
                    for i, line in enumerate(content.splitlines())
                )
                parts.append(f"\n# -- {tf_path} --\n{numbered}")
            except Exception:
                pass
        if parts:
            return "\n".join(parts)
    return ""


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set.")
        print("  Get key : https://aistudio.google.com/app/apikey")
        print("  Then run: export GEMINI_API_KEY=AIzaSy...")
        sys.exit(1)
    return key


# ============================================================================
# DATA EXTRACTION  (Checkov + Infracost -> plain text for prompt)
# ============================================================================

def extract_checkov_text(checkov_data):
    if not checkov_data:
        return "No Checkov data available."
    failed = checkov_data.get("results", {}).get("failed_checks", [])
    passed = checkov_data.get("results", {}).get("passed_checks", [])
    if not failed:
        return f"All checks passed ({len(passed)} checks)."
    lines = [f"Failed: {len(failed)}   Passed: {len(passed)}\n"]
    for check in failed:
        check_id   = check.get("check_id", "")
        check_name = check.get("check_name", "")
        resource   = check.get("resource", "")
        file_path  = check.get("file_path", "")
        line_range = check.get("file_line_range", [])
        code_block = check.get("code_block", [])
        loc = file_path
        if len(line_range) == 2:
            loc += f":{line_range[0]}-{line_range[1]}"
        lines.append(f"[{check_id}] {resource}  ({loc})")
        lines.append(f"  Rule: {check_name}")
        if code_block:
            snippet = "\n".join(f"  {ln}: {code.rstrip()}" for ln, code in code_block[:10])
            lines.append(f"  Code:\n{snippet}")
        lines.append("")
    return "\n".join(lines)


def _safe_float(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def _extract_resource_cost(resource):
    monthly = _safe_float(resource.get("monthlyCost"))
    components = []
    for cost in resource.get("costComponents", []):
        c = _safe_float(cost.get("monthlyCost"))
        if c == 0:
            c = _safe_float(cost.get("hourlyCost")) * 730
        monthly += c
        desc = cost.get("description", "")
        qty  = cost.get("monthlyQuantity") or cost.get("quantity") or ""
        unit = cost.get("unit", "")
        if desc:
            components.append(f"    * {desc}: {qty} {unit} = ${c:.2f}/mo")
    for sub in resource.get("subresources", []):
        sub_monthly = _safe_float(sub.get("monthlyCost"))
        for cost in sub.get("costComponents", []):
            sc = _safe_float(cost.get("monthlyCost"))
            if sc == 0:
                sc = _safe_float(cost.get("hourlyCost")) * 730
            sub_monthly += sc
        monthly += sub_monthly
    return monthly, components


def extract_infracost_text(infracost_data):
    if not infracost_data:
        return "No Infracost data available."
    total_monthly = _safe_float(infracost_data.get("totalMonthlyCost"))
    total_hourly  = _safe_float(infracost_data.get("totalHourlyCost"))
    if total_monthly == 0 and total_hourly > 0:
        total_monthly = total_hourly * 730
    lines = [f"Total monthly cost: ${total_monthly:.2f}  (annual: ${total_monthly*12:.2f})\n"]
    resource_costs = []
    for project in infracost_data.get("projects", []):
        proj_name = project.get("name", "")
        for section_key in ("breakdown", "diff"):
            section   = project.get(section_key, {})
            resources = section.get("resources", []) or project.get("resources", [])
            for resource in resources:
                name  = resource.get("name", "unknown")
                rtype = resource.get("resourceType", "")
                monthly, components = _extract_resource_cost(resource)
                if monthly == 0:
                    monthly = _safe_float(resource.get("hourlyCost")) * 730
                resource_costs.append((monthly, name, rtype, components, proj_name, section_key))
    seen: dict = {}
    for entry in resource_costs:
        monthly, name, *_ = entry
        if name not in seen or monthly > seen[name][0]:
            seen[name] = entry
    resource_costs = sorted(seen.values(), reverse=True)
    if not resource_costs:
        lines.append("No resources found in Infracost output.")
        lines.append("(Infracost may require INFRACOST_API_KEY or a valid cloud provider config.)")
        return "\n".join(lines)
    has_costs = any(m > 0 for m, *_ in resource_costs)
    if not has_costs:
        lines.append("All resources show $0.00 - Infracost could not price these resources.")
        lines.append("Possible causes:")
        lines.append("  1. INFRACOST_API_KEY not set or invalid.")
        lines.append("  2. Resources use variables Infracost cannot resolve.")
        lines.append("  3. Resources are free-tier or not yet supported.")
        lines.append("")
        lines.append("Resources found (unpriced):")
    for monthly, name, rtype, components, proj, section in resource_costs[:15]:
        label    = f"{name} ({rtype})" if rtype else name
        cost_str = f"${monthly:.2f}/mo" if monthly > 0 else "$0.00/mo (unpriced)"
        lines.append(f"{label}: {cost_str}")
        lines.extend(components[:4])
        lines.append("")
    return "\n".join(lines)


def extract_terraform_plan_text(tf_sources):
    if not tf_sources:
        return "No Terraform source available."
    return tf_sources[:12000]


# ============================================================================
# GEMINI PROMPT
# ============================================================================

ANALYSIS_PROMPT = """\
You are a senior cloud architect doing a COMPREHENSIVE security and cost review of Terraform infrastructure.

CRITICAL: You MUST find ALL vulnerabilities, not just summarize. Analyze every resource independently.

INPUT DATA:
1. Terraform source code (numbered lines) - analyze EVERY resource
2. Checkov security findings - already identified issues
3. Infracost cost analysis - resource costs

YOUR JOB - Three-part analysis:

PART 1: CHECKOV FINDINGS - Why they matter
For each Checkov failure:
- [CHECKOV] <check_id> - <resource> (file:line)
- Risk: <what attacker can do / business impact>
- Fix: <exact terraform code change>

PART 2: INDEPENDENT ANALYSIS - Find what Checkov might miss
Analyze terraform source for:
- Missing security controls (encryption, logging, versioning, MFA)
- Access control issues (public buckets, 0.0.0.0/0, overpermissive IAM)
- Compliance violations (no audit logs, no versioning, no KMS)
- Architectural weaknesses (single-AZ, no backups, no monitoring)
- Configuration risks specific to this deployment

For each issue found:
- [INDEPENDENT] <issue_category> - <resource> (file:line)
- Why it matters: <risk / compliance / cost impact>
- Fix: <terraform code change>

PART 3: COST OPTIMIZATION
For each expensive resource:
- [COST] <resource> (file:line)
- Current: <config> ($X/month estimated)
- Recommendation: <right-sizing suggestion>

OUTPUT FORMAT (MUST INCLUDE FILE:LINE):
```
CHECKOV FAILURES (from security scan):

[CHECKOV] CKV_AWS_24 - aws_security_group_rule.ingress[0] (terraform/ec2_module/main.tf:13-16)
Risk: SSH exposed to entire internet enables brute force attacks
Fix: cidr_blocks = ["10.0.0.0/8"]  # Restrict to corporate VPN

SECURITY ISSUES (from terraform analysis):

[INDEPENDENT] CRITICAL - Missing IMDSv2 (terraform/ec2_module/modules/ec2/ec2.tf:33-54)
Why: IMDSv1 vulnerable to SSRF attacks - attacker can extract credentials
Fix: Add inside resource block:
  metadata_options {
    http_tokens              = "required"
    http_put_response_hop_limit = 1
  }

[INDEPENDENT] CRITICAL - S3 Public Read-Write (terraform/s3_module/main.tf:5-7)
Why: Any unauthenticated user can read AND modify all data
Fix: acl = "private"

COST OPTIMIZATION:

[COST] m5.2xlarge instance (terraform/ec2_module/main.tf:9)
Currently: $277/month. Benchmark workload then consider m5.large ($70/mo) or t3.large ($60/mo)

```

RULES:
- EVERY finding MUST include file:line numbers
- NO exceptions to file:line requirement
- Analyze all resources in terraform source
- Don't repeat Checkov findings unless adding independent analysis
- Be specific: resource name, file path, line number
- Keep fixes to 1-3 lines of code maximum
- Mark estimates with "(estimated)" when using pricing

=====================================
TERRAFORM SOURCE CODE (with line numbers)
=====================================
{plan}

=====================================
CHECKOV SECURITY FINDINGS
=====================================
{security}

=====================================
INFRACOST COST IMPACT
=====================================
{cost}

---
ANALYZE EVERY RESOURCE. Find ALL vulnerabilities. Include file:line for EVERY finding.
"""


def build_prompt(plan_text, checkov_data, infracost_data):
    """Build optimized prompt for token efficiency."""
    checkov_summary = extract_checkov_summary(checkov_data)
    infracost_summary = extract_infracost_summary(infracost_data)

    return ANALYSIS_PROMPT.format(
        plan=plan_text[:8000],  # Limit terraform plan to 8000 chars
        security=checkov_summary,
        cost=infracost_summary,
    )



# ============================================================================
# GEMINI CALL
# ============================================================================

def ask_gemini(prompt, api_key):
    print("\n> Querying Gemini ...\n")
    client = genai.Client(api_key=api_key)
    for model_name in MODELS:
        print(f"  Trying {model_name} ... ", end="", flush=True)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"temperature": 0.1, "max_output_tokens": 8000},
            )
            text = response.text.strip()
            if text:
                print("OK")
                return text
            print("empty response")
        except Exception as e:
            print(f"failed -- {str(e)[:100]}")
    print("\nAll models failed.")
    return "Gemini analysis failed -- check API key and model availability."


# ============================================================================
# INLINE COMMENTS  (GitHub "Files changed" tab)
# ============================================================================

# Fix hints for every known Checkov check ID.
# Format: check_id -> (severity, plain-text fix instruction)
# No emojis or symbols anywhere.
CHECKOV_FIX_HINTS = {
    # EC2
    "CKV_AWS_8":    ("CRITICAL", "Root block device is not encrypted. Add: encrypted = true inside root_block_device."),
    "CKV_AWS_79":   ("HIGH",     "IMDSv2 is not enforced. Add: metadata_options { http_tokens = \"required\" http_endpoint = \"enabled\" }."),
    "CKV_AWS_126":  ("MEDIUM",   "Detailed CloudWatch monitoring is disabled. Change: monitoring = true."),
    "CKV_AWS_189":  ("MEDIUM",   "EBS volume is not gp3. Change: volume_type = \"gp3\"."),
    # EBS
    "CKV_AWS_3":    ("HIGH",     "EBS snapshot is not encrypted. Encrypt the source volume first so snapshots inherit encryption automatically."),
    "CKV_AWS_135":  ("CRITICAL", "EBS volume is not encrypted. Add: encrypted = true."),
    # S3
    "CKV_AWS_18":   ("HIGH",     "S3 access logging is not enabled. Add an aws_s3_bucket_logging resource pointing to a dedicated log bucket."),
    "CKV_AWS_19":   ("CRITICAL", "S3 bucket has no server-side encryption. Add aws_s3_bucket_server_side_encryption_configuration with sse_algorithm = \"AES256\"."),
    "CKV_AWS_20":   ("CRITICAL", "S3 bucket ACL allows public READ. Change: acl = \"private\"."),
    "CKV_AWS_21":   ("HIGH",     "S3 versioning is disabled. Add aws_s3_bucket_versioning with status = \"Enabled\"."),
    "CKV_AWS_52":   ("HIGH",     "S3 MFA delete is not enabled. Enable versioning first then enable mfa_delete."),
    "CKV2_AWS_6":   ("CRITICAL", "S3 public access block is missing. Set block_public_acls, block_public_policy, ignore_public_acls, restrict_public_buckets all to true."),
    "CKV2_AWS_61":  ("HIGH",     "S3 bucket has no lifecycle configuration. Add aws_s3_bucket_lifecycle_configuration to manage object expiry."),
    "CKV2_AWS_62":  ("HIGH",     "S3 event notifications are not configured. Add notification_configuration to the bucket resource."),
    # RDS
    "CKV_AWS_16":   ("CRITICAL", "RDS storage is not encrypted. Add: storage_encrypted = true."),
    "CKV_AWS_17":   ("CRITICAL", "RDS instance is publicly accessible. Change: publicly_accessible = false."),
    "CKV_AWS_23":   ("HIGH",     "RDS auto minor version upgrade is disabled. Add: auto_minor_version_upgrade = true."),
    "CKV_AWS_129":  ("HIGH",     "RDS CloudWatch logging is not enabled. Add: enabled_cloudwatch_logs_exports = [\"error\", \"slowquery\"]."),
    "CKV_AWS_133":  ("HIGH",     "RDS backup retention is too low. Change: backup_retention_period = 7 (minimum recommended)."),
    "CKV_AWS_161":  ("CRITICAL", "RDS has a hardcoded password. Remove the password attribute and add: manage_master_user_password = true."),
    "CKV_AWS_162":  ("HIGH",     "RDS IAM authentication is disabled. Add: iam_database_authentication_enabled = true."),
    "CKV_AWS_293":  ("CRITICAL", "RDS backup retention is 0 days - no recovery possible. Change: backup_retention_period = 7."),
    # Security Groups
    "CKV_AWS_24":   ("CRITICAL", "Security group allows SSH (port 22) from 0.0.0.0/0. Restrict cidr_blocks to your VPN or bastion CIDR, e.g. [\"10.0.0.0/8\"]."),
    "CKV_AWS_25":   ("CRITICAL", "Security group allows unrestricted ingress on a sensitive port. Replace cidr_blocks = [\"0.0.0.0/0\"] with security_groups referencing your app layer SG."),
    "CKV_AWS_260":  ("CRITICAL", "Security group allows HTTP (port 80) from 0.0.0.0/0. Restrict access or redirect HTTP to HTTPS."),
    "CKV2_AWS_5":   ("HIGH",     "Security group is defined but not attached to any resource. Verify it is in use or remove it."),
    # IAM
    "CKV_AWS_40":   ("CRITICAL", "IAM policy uses Action = \"*\". Replace with the minimum set of actions this role actually needs."),
    "CKV_AWS_355":  ("CRITICAL", "IAM policy uses Resource = \"*\". Scope to specific resource ARNs instead."),
    "CKV_AWS_274":  ("HIGH",     "IAM policy allows privilege escalation. Remove iam:PassRole or iam:* unless strictly required."),
    # VPC / Networking
    "CKV_AWS_130":  ("HIGH",     "Subnet assigns public IPs on launch. Add: map_public_ip_on_launch = false."),
    "CKV2_AWS_12":  ("MEDIUM",   "VPC default security group allows all traffic. Restrict the default SG to deny all inbound and outbound."),
    "CKV2_AWS_11":  ("MEDIUM",   "VPC flow logs are not enabled. Add an aws_flow_log resource for this VPC."),
    # CloudTrail
    "CKV_AWS_35":   ("HIGH",     "CloudTrail logs are not encrypted with KMS. Add: kms_key_id pointing to a customer-managed key."),
    "CKV_AWS_36":   ("HIGH",     "CloudTrail log file validation is disabled. Add: enable_log_file_validation = true."),
    # KMS
    "CKV_AWS_7":    ("HIGH",     "KMS key rotation is not enabled. Add: enable_key_rotation = true."),
    # Lambda
    "CKV_AWS_50":   ("HIGH",     "Lambda X-Ray tracing is disabled. Add: tracing_config { mode = \"Active\" }."),
    "CKV_AWS_116":  ("MEDIUM",   "Lambda has no dead letter queue. Add: dead_letter_config { target_arn = aws_sqs_queue.dlq.arn }."),
    # ALB / ELB
    "CKV_AWS_91":   ("HIGH",     "ALB access logging is disabled. Enable access_logs on the load balancer resource."),
    "CKV_AWS_92":   ("HIGH",     "ALB does not drop invalid HTTP headers. Add: drop_invalid_header_fields = true."),
    "CKV2_AWS_20":  ("HIGH",     "ALB does not redirect HTTP to HTTPS. Add an HTTP listener rule with a redirect action to port 443."),
    # EKS
    "CKV_AWS_58":   ("HIGH",     "EKS cluster secrets are not encrypted. Add encryption_config with a KMS key ARN."),
    "CKV_AWS_39":   ("MEDIUM",   "EKS API endpoint is publicly accessible. Add: endpoint_public_access = false."),
}

# Cost patterns: anchored regexes matched against individual .tf lines.
# Format: (regex, category, plain-text fix instruction)
COST_PATTERNS = [
    # EC2 instance types
    (r'instance_type\s*=\s*"m5\.2xlarge"',      "COST", "m5.2xlarge costs approx $277/mo. Benchmark workload then consider t3.large (~$60/mo) or m5.large (~$70/mo)."),
    (r'instance_type\s*=\s*"m5\.4xlarge"',      "COST", "m5.4xlarge costs approx $553/mo. Consider m5.xlarge (~$138/mo) after load testing."),
    (r'instance_type\s*=\s*"m5\.8xlarge"',      "COST", "m5.8xlarge costs approx $1,104/mo. Profile CPU and memory usage before keeping this size."),
    (r'instance_type\s*=\s*"m4\.',              "COST", "m4 family is previous generation. Switching to m5 or m6i gives better performance per dollar."),
    (r'instance_type\s*=\s*"r5\.2xlarge"',      "COST", "r5.2xlarge costs approx $378/mo. Consider r5.large (~$95/mo) unless memory metrics justify the larger size."),
    (r'instance_type\s*=\s*"r5\.4xlarge"',      "COST", "r5.4xlarge costs approx $756/mo. Downsize to r5.xlarge (~$189/mo) after reviewing memory usage."),
    # RDS instance classes
    (r'instance_class\s*=\s*"db\.r5\.2xlarge"', "COST", "db.r5.2xlarge costs approx $700/mo. Use db.t3.medium (~$60/mo) for dev or db.m5.large (~$140/mo) for light production."),
    (r'instance_class\s*=\s*"db\.r5\.4xlarge"', "COST", "db.r5.4xlarge costs approx $1,400/mo. Confirm memory-intensive workload requirements before keeping this class."),
    (r'instance_class\s*=\s*"db\.r5\.xlarge"',  "COST", "db.r5.xlarge costs approx $350/mo. Verify this size is needed based on actual query memory usage."),
    (r'instance_class\s*=\s*"db\.m5\.4xlarge"', "COST", "db.m5.4xlarge costs approx $576/mo. Consider db.m5.large (~$144/mo) unless benchmarks require more."),
    # EBS volume types
    (r'volume_type\s*=\s*"gp2"',               "COST", "gp2 is 20% more expensive than gp3 and has lower baseline IOPS. Change to: volume_type = \"gp3\"."),
    (r'storage_type\s*=\s*"gp2"',              "COST", "RDS gp2 storage is more expensive than gp3. Change to: storage_type = \"gp3\"."),
    # EBS and RDS storage sizes
    (r'volume_size\s*=\s*[5-9]\d{2}',          "COST", "Volume size is 500 GB or more, costing $50+/mo. Right-size to actual OS or data footprint (typically 20-50 GB for root volumes)."),
    (r'allocated_storage\s*=\s*[5-9]\d{2}',    "COST", "Allocated RDS storage is 500 GB or more (~$57+/mo). Reduce to actual database size plus a 20% buffer."),
    (r'allocated_storage\s*=\s*\d{4,}',        "COST", "Allocated RDS storage is 1,000 GB or more (~$115+/mo). Reduce to actual database size plus a 20% buffer."),
    # NAT Gateway
    (r'resource\s+"aws_nat_gateway"',           "COST", "NAT Gateway costs approx $35/mo fixed plus $0.045 per GB processed. Use VPC Endpoints for S3 or DynamoDB traffic to eliminate most of this cost."),
    # Unattached EBS volumes
    (r'resource\s+"aws_ebs_volume"',            "COST", "Standalone EBS volumes incur cost even when unattached. Confirm this volume is attached to an instance or remove it."),
    # RDS multi-AZ off
    (r'multi_az\s*=\s*false',                   "COST", "multi_az = false saves RDS cost but removes automatic failover. Enable for production: multi_az = true."),
    # Monitoring off
    (r'monitoring\s*=\s*false',                 "COST", "Detailed monitoring is disabled. Change to monitoring = true to get 1-minute CloudWatch metrics needed for right-sizing decisions."),
    # EBS not optimized
    (r'ebs_optimized\s*=\s*false',              "COST", "ebs_optimized = false disables dedicated EBS bandwidth. Change to ebs_optimized = true for consistent storage throughput."),
    # Backup retention 0 (RDS)
    (r'backup_retention_period\s*=\s*0',       "COST", "backup_retention_period = 0 means no backups - set to minimum 7 days for recovery."),
    # High memory instance with low usage
    (r'instance_type\s*=\s*"r[567]\.', "COST", "Memory-optimized instance (r-family) selected - verify memory actually needed vs t3/m5 family."),
    # NAT Gateway (expensive)
    (r'resource\s+"aws_nat_gateway"',          "COST", "NAT Gateway costs $32/month + data transfer. Consider VPC Endpoints for S3/DynamoDB to reduce costs."),
    # Unattached volumes
    (r'resource\s+"aws_ebs_volume"',           "COST", "Standalone EBS volume - verify it is attached, unattached volumes accrue cost."),
    # RDS backup window not set
    (r'resource\s+"aws_db_instance".*(?!backup_window)', "COST", "RDS backup window not specified - set backup_window for predictable backup times."),
]

# ============================================================================
# ENHANCED DATA EXTRACTION - Optimized for token efficiency
# ============================================================================

def extract_checkov_summary(checkov_data):
    """Extract critical info from Checkov output - minimal tokens."""
    if not checkov_data:
        return "No Checkov data available."

    failed = checkov_data.get("results", {}).get("failed_checks", [])
    passed = checkov_data.get("results", {}).get("passed_checks", [])

    if not failed:
        return f"✓ All checks passed ({len(passed)} checks)"

    # Group by severity for quick summary
    by_severity = {}
    for check in failed:
        check_id = check.get("check_id", "")
        resource = check.get("resource", "")
        file_path = check.get("file_path", "").split("/")[-1] if check.get("file_path") else "unknown"
        line_range = check.get("file_line_range", [])

        severity = _get_severity(check_id)
        if severity not in by_severity:
            by_severity[severity] = []

        loc = f"{file_path}" + (f":{line_range[0]}" if line_range else "")
        by_severity[severity].append(f"  [{check_id}] {resource} ({loc})")

    lines = [f"Failed: {len(failed)} | Passed: {len(passed)}\n"]
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if severity in by_severity:
            lines.append(f"{severity}:")
            lines.extend(by_severity[severity][:5])  # Max 5 per severity
            if len(by_severity[severity]) > 5:
                lines.append(f"  ... and {len(by_severity[severity])-5} more")

    return "\n".join(lines)


def extract_infracost_summary(infracost_data):
    """Extract cost impact - minimal tokens."""
    if not infracost_data:
        return "No Infracost data available."

    total = _safe_float(infracost_data.get("totalMonthlyCost"))
    if total == 0:
        return "Total monthly cost: $0.00 (unpriced resources or test environment)"

    lines = [f"Total monthly cost: ${total:.2f}/month (${total*12:.2f}/year)\n"]

    projects = infracost_data.get("projects", [])
    for proj in projects[:2]:  # Max 2 projects
        name = proj.get("name", "unknown")
        resources = proj.get("breakdown", {}).get("resources", [])
        if resources:
            resource_costs = []
            for res in resources:
                res_name = res.get("name", "")
                res_monthly, _ = _extract_resource_cost(res)
                if res_monthly > 0:
                    resource_costs.append((res_monthly, res_name))

            if resource_costs:
                resource_costs.sort(reverse=True)
                lines.append(f"{name}:")
                for monthly, res_name in resource_costs[:5]:
                    lines.append(f"  {res_name}: ${monthly:.2f}/mo")
                if len(resource_costs) > 5:
                    remaining = sum(m for m, _ in resource_costs[5:])
                    lines.append(f"  ... others: ${remaining:.2f}/mo")

    return "\n".join(lines)


# ============================================================================
# SECURITY PATTERNS - Terraform-specific vulnerability detection
# Generic patterns work across ANY AWS module or resource
# ============================================================================

SECURITY_PATTERNS = [
    # EC2 - IMDSv2 Enforcement
    (r'resource\s+"aws_instance"(?![\s\S]*?metadata_options[\s\S]*?http_tokens\s*=\s*"required")',
     "SECURITY", "EC2 lacks IMDSv2 enforcement - add: metadata_options { http_tokens = \"required\" http_put_response_hop_limit = 1 }"),

    # Any Storage - Encryption Disabled
    (r'encrypted\s*=\s*false',
     "SECURITY", "Storage not encrypted - change to: encrypted = true"),

    # Security Groups - Unrestricted Access Patterns
    (r'cidr_blocks\s*=\s*\[\s*"0\.0\.0\.0/0"\s*\]',
     "SECURITY", "Security group open to 0.0.0.0/0 - restrict to specific IPs/VPC CIDR"),

    # Security Groups - All Protocols
    (r'protocol\s*=\s*"-1"',
     "SECURITY", "All protocols allowed in security group rule - restrict to required protocols only"),

    # S3 - Public ACL (Read)
    (r'acl\s*=\s*"public-read(?!-write)"',
     "SECURITY", "S3 bucket public read - change to: acl = \"private\""),

    # S3 - Public ACL (Read-Write)
    (r'acl\s*=\s*"public-read-write"',
     "SECURITY", "S3 bucket public read-write (CRITICAL) - change to: acl = \"private\""),

    # S3 - Authenticated Users ACL
    (r'acl\s*=\s*"authenticated-read"',
     "SECURITY", "S3 ACL allows any AWS account - use private + bucket policy"),

    # IAM - Action Wildcard (Broad)
    (r'Action["\']?\s*:\s*\[?\s*["\']?\*["\']?\s*\]?',
     "SECURITY", "IAM uses Action = \"*\" - replace with minimum required actions"),

    # IAM - Resource Wildcard (Broad)
    (r'Resource["\']?\s*:\s*\[?\s*["\']?\*["\']?\s*\]?',
     "SECURITY", "IAM uses Resource = \"*\" - scope to specific ARNs"),

    # S3 - Default Encryption (AES256 vs KMS)
    (r'sse_algorithm\s*=\s*["\']AES256["\']',
     "SECURITY", "S3 uses AES256 - consider: sse_algorithm = \"aws:kms\""),

    # RDS - Publicly Accessible
    (r'publicly_accessible\s*=\s*true',
     "SECURITY", "RDS publicly accessible - change to: publicly_accessible = false"),

    # RDS - No Encryption
    (r'storage_encrypted\s*=\s*false',
     "SECURITY", "RDS not encrypted - add: storage_encrypted = true"),

    # Database - Weak Password/Hardcoded
    (r'password\s*=\s*["\'][^"\']+["\']',
     "SECURITY", "Hardcoded password found - use: manage_master_user_password = true"),

    # Lambda - Tracing Disabled
    (r'tracing_config.*mode.*=.*null|\bmode\s*=\s*"PassThrough"',
     "SECURITY", "Lambda X-Ray tracing disabled - add: mode = \"Active\""),

    # KMS - Key Rotation Disabled
    (r'enable_key_rotation\s*=\s*false',
     "SECURITY", "KMS key rotation disabled - enable: enable_key_rotation = true"),
]




def _get_severity(check_id):
    """Return plain-text severity for any Checkov check ID."""
    if check_id in CHECKOV_FIX_HINTS:
        return CHECKOV_FIX_HINTS[check_id][0]
    if check_id.startswith("CKV2_"):
        return "MEDIUM"
    return "HIGH"


def _get_fix(check_id, check_name, resource):
    """Return a fix instruction for any Checkov check ID, with a structured fallback."""
    if check_id in CHECKOV_FIX_HINTS:
        return CHECKOV_FIX_HINTS[check_id][1]
    return (
        f"Checkov rule '{check_name}' failed on '{resource}'. "
        f"Review the attribute flagged by {check_id} and apply the recommended configuration."
    )


def build_inline_comments(checkov_data, tf_sources_raw):
    """
    Build { path, line, body } dicts for GitHub's pulls.createReviewComment API.

    COMPREHENSIVE: Captures comments from:
    1. Checkov security failures - mapped to terraform lines
    2. Security patterns - detected by regex scanning
    3. Cost patterns - detected by regex scanning

    Each comment includes file:line for PR display.
    Sorted by severity, deduplicated, truncated for GitHub API limits.
    """
    comments = []
    seen = set()  # (path, line, key) - prevents duplicate comments on same line

    # Severity ranking for sorting (higher number = higher priority)
    severity_rank = {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
        "SECURITY": 2,
        "COST": 0,
    }

    # ── 1. CHECKOV: one comment per failed check ─────────────────────────────────
    print("  Processing Checkov findings...")
    failed = (checkov_data or {}).get("results", {}).get("failed_checks", [])

    for check in failed:
        check_id   = check.get("check_id", "")
        file_path  = check.get("file_path", "").lstrip("/").lstrip("./")
        line_range = check.get("file_line_range", [])
        check_name = check.get("check_name", "")
        resource   = check.get("resource", "")
        code_block = check.get("code_block", [])

        if not file_path or not line_range:
            continue

        # Pin to the last line of the failing block
        line = line_range[1] if len(line_range) == 2 else line_range[0]

        dedup_key = (file_path, line, check_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        severity = _get_severity(check_id)
        fix      = _get_fix(check_id, check_name, resource)

        # Include code snippet
        snippet_section = ""
        if code_block:
            snippet_lines = [f"    {ln}  {code.rstrip()}" for ln, code in code_block[:5]]
            snippet_section = (
                "\n\nCode (lines {}-{}):\n```hcl\n".format(line_range[0], line_range[1] if len(line_range) == 2 else line_range[0])
                + "\n".join(snippet_lines)
                + "\n```"
            )

        body = (
            f"[{severity}] {check_id} - {resource}\n\n"
            f"Issue: {check_name}\n\n"
            f"Fix: {fix}"
            f"{snippet_section}"
        )
        comments.append({
            "path": file_path,
            "line": line,
            "body": body,
            "severity": severity_rank.get(severity, 0),
            "source": "checkov"
        })

    # ── 2. SECURITY PATTERNS: scan all terraform files ──────────────────────────
    print("  Scanning security patterns...")
    for search_dir in ["terraform", "."]:
        base = Path(search_dir)
        if not base.is_dir():
            continue
        tf_files = sorted(base.rglob("*.tf"))
        if not tf_files:
            continue

        for tf_path in tf_files:
            try:
                rel_path   = str(tf_path).lstrip("/").lstrip("./")
                file_lines = tf_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for lineno, raw_line in enumerate(file_lines, start=1):
                stripped = raw_line.strip()
                if stripped.startswith("#"):
                    continue
                for pattern, category, hint in SECURITY_PATTERNS:
                    if re.search(pattern, stripped, re.IGNORECASE|re.MULTILINE):
                        dedup_key = (rel_path, lineno, f"sec_{pattern[:20]}")
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        body = (
                            f"[{category}] Security Issue - Line {lineno}\n\n"
                            f"Code: {stripped[:80]}\n\n"
                            f"Issue: {hint}"
                        )
                        comments.append({
                            "path": rel_path,
                            "line": lineno,
                            "body": body,
                            "severity": severity_rank.get(category, 1),
                            "source": "security_pattern"
                        })
        break

    # ── 3. COST PATTERNS: scan all terraform files ─────────────────────────────
    print("  Scanning cost patterns...")
    for search_dir in ["terraform", "."]:
        base = Path(search_dir)
        if not base.is_dir():
            continue
        tf_files = sorted(base.rglob("*.tf"))
        if not tf_files:
            continue

        for tf_path in tf_files:
            try:
                rel_path   = str(tf_path).lstrip("/").lstrip("./")
                file_lines = tf_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for lineno, raw_line in enumerate(file_lines, start=1):
                stripped = raw_line.strip()
                if stripped.startswith("#"):
                    continue
                for pattern, category, hint in COST_PATTERNS:
                    if re.search(pattern, stripped, re.IGNORECASE):
                        dedup_key = (rel_path, lineno, f"cost_{pattern[:20]}")
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        body = (
                            f"[{category}] Cost Optimization - Line {lineno}\n\n"
                            f"Code: {stripped[:80]}\n\n"
                            f"Suggestion: {hint}"
                        )
                        comments.append({
                            "path": rel_path,
                            "line": lineno,
                            "body": body,
                            "severity": severity_rank.get(category, 0),
                            "source": "cost_pattern"
                        })

        break

    # ── 4. Sort by severity (high first), then line number (ascending) ──────────
    print(f"  Sorting {len(comments)} comments...")
    comments.sort(key=lambda c: (-c["severity"], c["line"]))

    # ── 5. Deduplicate same line (keep highest severity) ─────────────────────────
    final_comments = []
    seen_lines = {}  # path:line -> comment

    for comment in comments:
        line_key = f"{comment['path']}:{comment['line']}"
        if line_key not in seen_lines:
            seen_lines[line_key] = comment
        else:
            # Keep highest severity
            if comment["severity"] > seen_lines[line_key]["severity"]:
                final_comments.remove(seen_lines[line_key])
                final_comments.append(comment)
                seen_lines[line_key] = comment
            # else: keep existing (lower severity) - GitHub shows first one users sees

    comments = final_comments if final_comments else comments

    # ── 6. Truncate long comments to 4000 chars (GitHub API limit) ───────────────
    for comment in comments:
        if len(comment["body"]) > 4000:
            comment["body"] = (
                comment["body"][:3970] +
                "\n\n[Comment truncated - see PR summary for full analysis]"
            )
        # Remove internal tracking fields
        del comment["severity"]
        del comment["source"]

    print(f"  Generated {len(comments)} inline comments")
    return comments




def save_inline_comments(comments, output_dir="."):
    path = f"{output_dir}/inline-comments.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(comments, f, indent=2)
        print(f"  Saved: {path}  ({len(comments)} inline comments)")
    except Exception as e:
        print(f"  Could not save inline-comments.json: {e}")


# ============================================================================
# REPORT SAVE
# ============================================================================

def save_report(report, output_dir="."):
    md_path = f"{output_dir}/infrastructure-analysis-report.md"
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report)
            f.write(
                f"\n\n---\n*Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                " -- Checkov + Infracost + Gemini*\n"
            )
        print(f"\n  Saved: {md_path}")
    except Exception as e:
        print(f"\n  Could not save markdown: {e}")

    json_path = f"{output_dir}/infrastructure-analysis-report.json"
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "report": report}, f, indent=2)
        print(f"  Saved: {json_path}")
    except Exception as e:
        print(f"  Could not save JSON: {e}")

    txt_path = f"{output_dir}/infrastructure-analysis-summary.txt"
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report[:800])
        print(f"  Saved: {txt_path}")
    except Exception as e:
        print(f"  Could not save summary: {e}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    api_key = get_gemini_key()

    for required in ["checkov-output.json", "infracost-output.json"]:
        if not os.path.exists(required):
            print(f"Error: {required} not found.")
            print("Run Checkov and Infracost before calling this script.")
            sys.exit(1)

    print("> Loading checkov-output.json ...")
    checkov_data = load_json_file("checkov-output.json")

    print("> Loading infracost-output.json ...")
    infracost_data = load_json_file("infracost-output.json")

    print("> Loading Terraform source files ...")
    tf_sources = load_terraform_sources()

    if not checkov_data:
        print("Error: Failed to parse checkov-output.json")
        sys.exit(1)
    if not infracost_data:
        print("Error: Failed to parse infracost-output.json")
        sys.exit(1)

    plan_text = extract_terraform_plan_text(tf_sources)

    # Build optimized prompt with summarized data (not full text)
    prompt = build_prompt(plan_text, checkov_data, infracost_data)

    print(f"\n> Prompt size: {len(prompt)} chars (optimized for free tier)")
    report = ask_gemini(prompt, api_key)

    print("\n> Saving reports ...")
    save_report(report)

    print("\n> Building inline comments ...")
    inline_comments = build_inline_comments(checkov_data, tf_sources)
    save_inline_comments(inline_comments)

    print("\nDone.")
    print("  infrastructure-analysis-report.md   <- PR summary comment")
    print("  infrastructure-analysis-report.json <- artifact")
    print("  infrastructure-analysis-summary.txt <- notification snippet")
    print(f"  inline-comments.json                <- {len(inline_comments)} file-line comments")



if __name__ == "__main__":
    main()