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
You are a senior cloud architect reviewing a Terraform pull request.
 
Inputs:
1. Terraform plan
2. Checkov security scan results
3. Infracost cost difference report
 
Your job is to analyze the infrastructure changes.
 
For each issue provide:
- Finding
- Risk
- Cost Impact
- Root Cause
- Solution
- Steps to Fix
- Terraform Fix Example
 
Organize output under these sections:
- Infrastructure Changes
- Security Issues
- Cost Impact
- Reliability Concerns
- Architecture Anti-Patterns
 
Use this exact format for every issue:
 
---
 
**Finding:** <title>
**Risk:** <what can go wrong>
**Cost Impact:** <dollar amount or "None">
**Root Cause:** <why this exists in the code - include resource name and file:line>
**Solution:** <what to do>
**Steps to Fix:**
1. <step>
2. <step>
3. <step>
**Terraform Fix Example:**
```hcl
<corrected resource block - only the changed attributes>
```
 
---
 
Rules:
- Output ONLY the five section headers and the issue blocks under them.
- No introductions, no conclusions, no summaries outside the blocks.
- Reference the exact resource name and file:line from the inputs for every finding.
- Keep each field to 1-2 sentences maximum.
- If a section has no issues write: *(none)*
 
=====================================
TERRAFORM PLAN
=====================================
{plan}
 
=====================================
CHECKOV RESULTS
=====================================
{security}
 
=====================================
INFRACOST DIFF
=====================================
{cost}
 
IMPORTANT: If resources show "$0.00 (unpriced)", Infracost could not fetch live prices.
Use the Terraform source above to estimate costs based on AWS on-demand pricing for
us-east-1 and mark estimates with "(estimated)". Never write "None" for Cost Impact
if the resource is clearly billable.
"""
 
 
def build_prompt(plan_text, checkov_text, infracost_text):
    return ANALYSIS_PROMPT.format(
        plan=plan_text,
        security=checkov_text,
        cost=infracost_text,
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
 
    Security: one comment per Checkov failed_check, pinned to the exact
              failing line Checkov reported. Every check ID is handled -
              known ones get a specific fix hint, unknown ones get a
              structured fallback from the check name and resource name.
    Cost:     one comment per matching line in every .tf file, pinned to
              that exact line number.
    Plain text only - no emojis or special symbols.
    """
    comments = []
    seen = set()  # (path, line, key) - prevents duplicate comments on same line
 
    # ── 1. Security: one comment per Checkov failed check ────────────────────
    failed = (checkov_data or {}).get("results", {}).get("failed_checks", [])
 
    for check in failed:
        check_id   = check.get("check_id", "")
        file_path  = check.get("file_path", "").lstrip("/").lstrip("./")
        line_range = check.get("file_line_range", [])
        check_name = check.get("check_name", "")
        resource   = check.get("resource", "")
        code_block = check.get("code_block", [])  # [[lineno, text], ...]
 
        if not file_path or not line_range:
            continue
 
        # Pin to the last line of the failing block so the comment sits at
        # the closing brace, which is always visible in the diff.
        line = line_range[1] if len(line_range) == 2 else line_range[0]
 
        dedup_key = (file_path, line, check_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
 
        severity = _get_severity(check_id)
        fix      = _get_fix(check_id, check_name, resource)
 
        # Include the offending code snippet that Checkov captured
        snippet_section = ""
        if code_block:
            snippet_lines = [f"    {ln}  {code.rstrip()}" for ln, code in code_block[:6]]
            snippet_section = (
                "\n\nOffending code:\n```hcl\n"
                + "\n".join(snippet_lines)
                + "\n```"
            )
 
        body = (
            f"[{severity}] {check_id} on {resource}\n\n"
            f"Issue: {check_name}\n\n"
            f"Fix: {fix}"
            f"{snippet_section}"
        )
        comments.append({"path": file_path, "line": line, "body": body})
 
    # ── 2. Cost: scan every .tf file line by line ─────────────────────────────
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
                if stripped.startswith("#"):  # skip comment-only lines
                    continue
                for pattern, category, hint in COST_PATTERNS:
                    if re.search(pattern, stripped, re.IGNORECASE):
                        dedup_key = (rel_path, lineno, pattern)
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        body = (
                            f"[{category}] {rel_path} line {lineno}\n\n"
                            f"Current: {stripped}\n\n"
                            f"Suggestion: {hint}"
                        )
                        comments.append({"path": rel_path, "line": lineno, "body": body})
 
        break  # stop after first directory that contains .tf files
 
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
 
    if infracost_data:
        projects = infracost_data.get("projects", [])
        print(f"  totalMonthlyCost : {infracost_data.get('totalMonthlyCost', 'missing')}")
        print(f"  projects found   : {len(projects)}")
        for i, p in enumerate(projects[:3]):
            print(f"  project[{i}] breakdown resources: {len(p.get('breakdown', {}).get('resources', []))}")
            print(f"  project[{i}] diff     resources: {len(p.get('diff', {}).get('resources', []))}")
 
    print("> Loading Terraform source files ...")
    tf_sources = load_terraform_sources()
 
    if not checkov_data:
        print("Error: Failed to parse checkov-output.json")
        sys.exit(1)
    if not infracost_data:
        print("Error: Failed to parse infracost-output.json")
        sys.exit(1)
 
    plan_text      = extract_terraform_plan_text(tf_sources)
    checkov_text   = extract_checkov_text(checkov_data)
    infracost_text = extract_infracost_text(infracost_data)
 
    prompt = build_prompt(plan_text, checkov_text, infracost_text)
    report = ask_gemini(prompt, api_key)
 
    print("\n> Saving reports ...")
    save_report(report)
 
    print("\n> Building inline comments ...")
    inline_comments = build_inline_comments(checkov_data, tf_sources)  # FIX: pass both arguments
    save_inline_comments(inline_comments)
 
    print("\nDone.")
    print("  infrastructure-analysis-report.md   <- PR summary comment")
    print("  infrastructure-analysis-report.json <- artifact")
    print("  infrastructure-analysis-summary.txt <- notification snippet")
    print("  inline-comments.json                <- Files changed tab comments")
 
 
if __name__ == "__main__":
    main()