#!/usr/bin/env python3
"""
Infrastructure Analysis Script
Reads Checkov + Infracost output, calls Claude via Anthropic API,
posts a PR summary comment and inline file-changed-tab comments.
"""

import os
import sys
import json
import re
import time
import textwrap
from pathlib import Path
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("anthropic SDK is not installed. Run: pip install anthropic")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Model to use for analysis
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Output files
OUTPUT_MD   = "infrastructure-analysis-report.md"
OUTPUT_JSON = "infrastructure-analysis-report.json"
OUTPUT_TXT  = "infrastructure-analysis-summary.txt"
OUTPUT_INLINE = "inline-comments.json"


# ============================================================================
# FILE LOADING
# ============================================================================

def load_json_file(filename: str) -> dict | None:
    for encoding in ["utf-8-sig", "utf-16", "utf-16-le", "utf-8", "latin-1"]:
        try:
            with open(filename, "r", encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    print(f"  ERROR: Could not parse {filename}")
    return None


def load_terraform_sources(terraform_dir: str = "terraform") -> str:
    """Load all .tf files, returning numbered content for the AI prompt."""
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


def get_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY not set.")
        print("  Get key: https://console.anthropic.com/")
        print("  Then:    export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    return key


# ============================================================================
# DATA EXTRACTION  (Checkov + Infracost -> plain text for prompt)
# ============================================================================

def extract_checkov_text(checkov_data: dict) -> str:
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


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def extract_infracost_text(infracost_data: dict) -> str:
    """
    BUG FIX: previous version iterated both 'breakdown' and 'diff' sections,
    causing double-counting. We now use only 'breakdown' (the total monthly cost
    snapshot) and fall back to 'diff' only if 'breakdown' is absent.
    """
    if not infracost_data:
        return "No Infracost data available."

    total_monthly = _safe_float(infracost_data.get("totalMonthlyCost"))
    total_hourly  = _safe_float(infracost_data.get("totalHourlyCost"))
    if total_monthly == 0 and total_hourly > 0:
        total_monthly = total_hourly * 730

    lines = [f"Total monthly cost: ${total_monthly:.2f}  (annual: ${total_monthly * 12:.2f})\n"]

    resource_costs: list[tuple] = []
    for project in infracost_data.get("projects", []):
        # BUG FIX: prefer 'breakdown' over 'diff' — 'diff' shows the *change*, not total cost
        section = project.get("breakdown") or project.get("diff", {})
        for resource in section.get("resources", []):
            name  = resource.get("name", "unknown")
            rtype = resource.get("resourceType", "")
            monthly = _safe_float(resource.get("monthlyCost"))
            if monthly == 0:
                monthly = _safe_float(resource.get("hourlyCost")) * 730
            components = []
            for cost in resource.get("costComponents", []):
                c = _safe_float(cost.get("monthlyCost"))
                if c == 0:
                    c = _safe_float(cost.get("hourlyCost")) * 730
                desc = cost.get("description", "")
                qty  = cost.get("monthlyQuantity") or cost.get("quantity") or ""
                unit = cost.get("unit", "")
                if desc:
                    components.append(f"    * {desc}: {qty} {unit} = ${c:.2f}/mo")
            resource_costs.append((monthly, name, rtype, components))

    # Deduplicate by name, keeping highest monthly cost entry
    seen: dict[str, tuple] = {}
    for entry in resource_costs:
        name = entry[1]
        if name not in seen or entry[0] > seen[name][0]:
            seen[name] = entry

    resource_costs = sorted(seen.values(), key=lambda x: x[0], reverse=True)

    if not resource_costs:
        lines.append("No resources found in Infracost output.")
        lines.append("(Infracost may require INFRACOST_API_KEY or a valid cloud provider config.)")
        return "\n".join(lines)

    has_costs = any(m > 0 for m, *_ in resource_costs)
    if not has_costs:
        lines.append("All resources show $0.00 — Infracost could not price these resources.")
        lines.append("Possible causes:")
        lines.append("  1. INFRACOST_API_KEY not set or invalid.")
        lines.append("  2. Resources use variables Infracost cannot resolve.")
        lines.append("  3. Resources are free-tier or not yet supported.")
        lines.append("")
        lines.append("Resources found (unpriced):")

    for monthly, name, rtype, components in resource_costs[:20]:
        label    = f"{name} ({rtype})" if rtype else name
        cost_str = f"${monthly:.2f}/mo" if monthly > 0 else "$0.00/mo (unpriced)"
        lines.append(f"{label}: {cost_str}")
        lines.extend(components[:4])
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# CLAUDE PROMPT
# ============================================================================

ANALYSIS_PROMPT = """\
You are a senior cloud architect reviewing a Terraform pull request.

Inputs:
1. Terraform source (with line numbers)
2. Checkov security scan results
3. Infracost cost report

Your job: identify every misconfiguration, security risk, and cost issue.

For each finding use EXACTLY this format:

---

**Finding:** <concise title>
**Severity:** CRITICAL | HIGH | MEDIUM | LOW
**Risk:** <what can go wrong — 1-2 sentences>
**Cost Impact:** <dollar amount, or "None">
**Root Cause:** <resource name and file:line — be specific>
**Solution:** <what to change — 1-2 sentences>
**Steps to Fix:**
1. <step>
2. <step>
**Terraform Fix Example:**
```hcl
<only the changed attributes — not the full resource>
```

---

Organise all findings under these five headers (write the header even if there are no findings):

## Infrastructure Changes
## Security Issues
## Cost Impact
## Reliability Concerns
## Architecture Anti-Patterns

Rules:
- Reference exact resource name and file:line for every finding.
- If a section has no issues write: *(none)*
- No introductions, preambles, or conclusions outside the blocks.
- Keep every field to 1-2 sentences maximum.
- For S3: check for missing public-access-block, SSE encryption, versioning,
  access logging, lifecycle rules, event notifications, and HTTPS-only policy.
- For EC2: check for open SSH/RDP, missing IMDSv2, unencrypted EBS, missing
  VPC assignment, silent CloudWatch alarms (no SNS action), and monitoring=false.
- For cost: flag gp2 volumes (switch to gp3), oversized instance types,
  unattached EIPs ($3.65/mo each), and NAT Gateway data charges.

=====================================
TERRAFORM SOURCE
=====================================
{plan}

=====================================
CHECKOV RESULTS
=====================================
{security}

=====================================
INFRACOST REPORT
=====================================
{cost}

IMPORTANT: If Infracost shows $0.00 for billable resources, estimate costs
from AWS on-demand us-east-1 pricing and mark with "(estimated)".
"""


def build_prompt(plan_text: str, checkov_text: str, infracost_text: str) -> str:
    return ANALYSIS_PROMPT.format(
        plan=plan_text[:14000],  # stay within token budget
        security=checkov_text,
        cost=infracost_text,
    )


# ============================================================================
# CLAUDE API CALL  (with retry)
# ============================================================================

def ask_claude(prompt: str, api_key: str) -> str:
    print(f"\n  Calling Claude ({CLAUDE_MODEL}) ...", flush=True)
    client = anthropic.Anthropic(api_key=api_key)

    for attempt in range(3):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            if text:
                print("  Claude responded OK.")
                return text
            print(f"  Attempt {attempt+1}: empty response — retrying ...")
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"  Rate-limited — waiting {wait}s ...")
            time.sleep(wait)
        except anthropic.APIError as e:
            print(f"  API error on attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5)

    return "Claude analysis failed — check ANTHROPIC_API_KEY and model availability."


# ============================================================================
# INLINE COMMENTS  (GitHub "Files changed" tab)
# ============================================================================

# ── Checkov fix hints ────────────────────────────────────────────────────────
# Format: check_id -> (severity, plain-text fix instruction)
CHECKOV_FIX_HINTS: dict[str, tuple[str, str]] = {
    # EC2
    "CKV_AWS_8":    ("CRITICAL", "Root block device is not encrypted. Add: encrypted = true inside root_block_device."),
    "CKV_AWS_79":   ("HIGH",     "IMDSv2 is not enforced. Add: metadata_options { http_tokens = \"required\" http_endpoint = \"enabled\" }."),
    "CKV_AWS_126":  ("MEDIUM",   "Detailed CloudWatch monitoring is disabled. Change: monitoring = true."),
    "CKV_AWS_189":  ("MEDIUM",   "EBS volume is not gp3. Change: volume_type = \"gp3\"."),
    # EBS
    "CKV_AWS_3":    ("HIGH",     "EBS snapshot is not encrypted. Encrypt the source volume so snapshots inherit encryption."),
    "CKV_AWS_135":  ("CRITICAL", "EBS volume is not encrypted. Add: encrypted = true."),
    # S3
    "CKV_AWS_18":   ("HIGH",     "S3 access logging is disabled. Add aws_s3_bucket_logging pointing to a dedicated log bucket."),
    "CKV_AWS_19":   ("CRITICAL", "S3 bucket has no server-side encryption. Add aws_s3_bucket_server_side_encryption_configuration with sse_algorithm = \"AES256\"."),
    "CKV_AWS_20":   ("CRITICAL", "S3 bucket ACL allows public READ. Change: acl = \"private\" or remove the ACL resource."),
    "CKV_AWS_21":   ("HIGH",     "S3 versioning is disabled. Add aws_s3_bucket_versioning with status = \"Enabled\"."),
    "CKV_AWS_52":   ("HIGH",     "S3 MFA delete is not enabled. Enable versioning first, then set mfa_delete = \"Enabled\"."),
    "CKV_AWS_144":  ("MEDIUM",   "S3 cross-region replication is not configured. Add replication_configuration if DR is required."),
    "CKV_AWS_145":  ("HIGH",     "S3 bucket uses SSE-S3, not SSE-KMS. Change sse_algorithm to \"aws:kms\" and supply kms_master_key_id."),
    "CKV2_AWS_6":   ("CRITICAL", "S3 public access block is missing. Set block_public_acls, block_public_policy, ignore_public_acls, restrict_public_buckets all to true."),
    "CKV2_AWS_61":  ("HIGH",     "S3 bucket has no lifecycle configuration. Add aws_s3_bucket_lifecycle_configuration to manage object expiry and tiering."),
    "CKV2_AWS_62":  ("HIGH",     "S3 event notifications are not configured. Add notification_configuration to route events to SNS, SQS, or Lambda."),
    # Security Groups
    "CKV_AWS_24":   ("CRITICAL", "Security group allows SSH (port 22) from 0.0.0.0/0. Restrict cidr_blocks to your VPN or bastion CIDR, e.g. [\"10.0.0.0/8\"]."),
    "CKV_AWS_25":   ("CRITICAL", "Security group allows unrestricted ingress. Replace cidr_blocks = [\"0.0.0.0/0\"] with a scoped CIDR or security group reference."),
    "CKV_AWS_260":  ("CRITICAL", "Security group allows HTTP (port 80) from 0.0.0.0/0. Restrict access or redirect HTTP to HTTPS at the ALB layer."),
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
    # RDS
    "CKV_AWS_16":   ("CRITICAL", "RDS storage is not encrypted. Add: storage_encrypted = true."),
    "CKV_AWS_17":   ("CRITICAL", "RDS instance is publicly accessible. Change: publicly_accessible = false."),
    "CKV_AWS_293":  ("CRITICAL", "RDS backup retention is 0 days. Change: backup_retention_period = 7."),
    "CKV_AWS_161":  ("CRITICAL", "RDS has a hardcoded password. Remove the password attribute and add: manage_master_user_password = true."),
    "CKV_AWS_133":  ("HIGH",     "RDS backup retention is too low. Change: backup_retention_period = 7 (minimum recommended)."),
    "CKV_AWS_162":  ("HIGH",     "RDS IAM authentication is disabled. Add: iam_database_authentication_enabled = true."),
}

# ── Cost patterns: matched against individual .tf lines ──────────────────────
COST_PATTERNS: list[tuple[str, str, str]] = [
    # EC2 instance types
    (r'instance_type\s*=\s*"m5\.2xlarge"',      "COST", "m5.2xlarge costs approx $277/mo. After load testing consider t3.large (~$60/mo) or m5.large (~$70/mo)."),
    (r'instance_type\s*=\s*"m5\.4xlarge"',      "COST", "m5.4xlarge costs approx $553/mo. Consider m5.xlarge (~$138/mo) after profiling."),
    (r'instance_type\s*=\s*"m5\.8xlarge"',      "COST", "m5.8xlarge costs approx $1,104/mo. Profile CPU and memory before keeping this size."),
    (r'instance_type\s*=\s*"m4\.',              "COST", "m4 family is previous generation. Switch to m5 or m6i for better price-performance."),
    (r'instance_type\s*=\s*"r5\.2xlarge"',      "COST", "r5.2xlarge costs approx $378/mo. Consider r5.large (~$95/mo) unless memory metrics justify the size."),
    (r'instance_type\s*=\s*"r5\.4xlarge"',      "COST", "r5.4xlarge costs approx $756/mo. Downsize to r5.xlarge (~$189/mo) after reviewing memory usage."),
    # RDS instance classes
    (r'instance_class\s*=\s*"db\.r5\.2xlarge"', "COST", "db.r5.2xlarge costs approx $700/mo. Use db.t3.medium (~$60/mo) for dev or db.m5.large for light prod."),
    (r'instance_class\s*=\s*"db\.r5\.4xlarge"', "COST", "db.r5.4xlarge costs approx $1,400/mo. Confirm memory-intensive requirements before keeping."),
    (r'instance_class\s*=\s*"db\.r5\.xlarge"',  "COST", "db.r5.xlarge costs approx $350/mo. Verify query memory requirements."),
    (r'instance_class\s*=\s*"db\.m5\.4xlarge"', "COST", "db.m5.4xlarge costs approx $576/mo. Consider db.m5.large (~$144/mo) unless benchmarked otherwise."),
    # EBS volume types
    (r'volume_type\s*=\s*"gp2"',               "COST", "gp2 is 20% more expensive than gp3 and has lower baseline IOPS. Change to: volume_type = \"gp3\"."),
    (r'storage_type\s*=\s*"gp2"',              "COST", "RDS gp2 storage costs more than gp3. Change to: storage_type = \"gp3\"."),
    # EBS sizes
    (r'volume_size\s*=\s*[5-9]\d{2}',          "COST", "Volume is 500 GB or more (~$50+/mo). Right-size to actual data footprint (typically 20-50 GB for root)."),
    (r'allocated_storage\s*=\s*[5-9]\d{2}',    "COST", "RDS allocated storage is 500 GB+ (~$57+/mo). Reduce to actual DB size plus 20% buffer."),
    (r'allocated_storage\s*=\s*\d{4,}',        "COST", "RDS allocated storage is 1,000 GB+ (~$115+/mo). Reduce to actual DB size plus 20% buffer."),
    # S3 storage class hints
    (r'storage_class\s*=\s*"STANDARD"',        "COST", "S3 STANDARD storage costs $0.023/GB/mo. For infrequently accessed data use INTELLIGENT_TIERING or STANDARD_IA."),
    # NAT Gateway
    (r'resource\s+"aws_nat_gateway"',           "COST", "NAT Gateway costs ~$35/mo fixed plus $0.045/GB processed. Add VPC Endpoints for S3 or DynamoDB to reduce data charges."),
    # Unattached EBS
    (r'resource\s+"aws_ebs_volume"',            "COST", "Standalone EBS volumes incur cost even when unattached. Confirm this volume is attached or remove it."),
    # RDS multi-AZ
    (r'multi_az\s*=\s*false',                  "COST", "multi_az = false saves RDS cost but removes automatic failover. Enable for production: multi_az = true."),
    # Monitoring
    (r'monitoring\s*=\s*false',                "COST", "Detailed monitoring is disabled. Change to monitoring = true for 1-minute CloudWatch metrics needed for right-sizing."),
    # EBS optimized
    (r'ebs_optimized\s*=\s*false',             "COST", "ebs_optimized = false disables dedicated EBS bandwidth. Change to ebs_optimized = true."),
    # EIP
    (r'resource\s+"aws_eip"',                  "COST", "Elastic IPs cost $3.65/mo when attached and $0.005/hr when unattached. Confirm this EIP is in use."),
]


def _get_severity(check_id: str) -> str:
    if check_id in CHECKOV_FIX_HINTS:
        return CHECKOV_FIX_HINTS[check_id][0]
    if check_id.startswith("CKV2_"):
        return "MEDIUM"
    return "HIGH"


def _get_fix(check_id: str, check_name: str, resource: str) -> str:
    if check_id in CHECKOV_FIX_HINTS:
        return CHECKOV_FIX_HINTS[check_id][1]
    return (
        f"Checkov rule '{check_name}' failed on '{resource}'. "
        f"Review the attribute flagged by {check_id} and apply the recommended configuration."
    )


def build_inline_comments(checkov_data: dict, _tf_sources_raw: str) -> list[dict]:
    """
    Return list of { path, line, body } dicts for GitHub's createReviewComment API.

    Security: one comment per Checkov failed_check, pinned to the failing line.
    Cost:     one comment per matching line across all .tf files.
    """
    comments: list[dict] = []
    seen: set[tuple] = set()

    # ── 1. Security: Checkov failed checks ───────────────────────────────────
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

        # Pin to last line of failing block (always visible in the diff)
        line = line_range[1] if len(line_range) == 2 else line_range[0]

        dedup_key = (file_path, line, check_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        severity = _get_severity(check_id)
        fix      = _get_fix(check_id, check_name, resource)

        snippet_section = ""
        if code_block:
            snippet_lines = [f"    {ln}  {code.rstrip()}" for ln, code in code_block[:6]]
            snippet_section = (
                "\n\nOffending code:\n```hcl\n"
                + "\n".join(snippet_lines)
                + "\n```"
            )

        body = (
            f"[{severity}] {check_id} — {resource}\n\n"
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
                if stripped.startswith("#"):
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
        break  # stop after first directory that has .tf files

    return comments


# ============================================================================
# REPORT SAVING
# ============================================================================

def _truncate_for_github(text: str, max_chars: int = 64000) -> str:
    """
    BUG FIX: original used `head -c 65000` which could cut mid-line or mid-table.
    This version truncates cleanly on a section boundary.
    """
    if len(text) <= max_chars:
        return text
    cutoff = text.rfind("\n---\n", 0, max_chars)
    if cutoff == -1:
        cutoff = text.rfind("\n", 0, max_chars)
    truncated = text[:cutoff] if cutoff > 0 else text[:max_chars]
    return truncated + "\n\n**[Report truncated — see workflow artifacts for full details]**"


def save_report(report: str, output_dir: str = ".") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer    = f"\n\n---\n*Generated {timestamp} — Checkov + Infracost + Claude*\n"

    # BUG FIX: previous version used hardcoded "." instead of output_dir for all paths
    md_path = os.path.join(output_dir, OUTPUT_MD)
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report)
            f.write(footer)
        print(f"  Saved: {md_path}")
    except Exception as e:
        print(f"  Could not save markdown: {e}")

    json_path = os.path.join(output_dir, OUTPUT_JSON)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "report": report}, f, indent=2)
        print(f"  Saved: {json_path}")
    except Exception as e:
        print(f"  Could not save JSON: {e}")

    txt_path = os.path.join(output_dir, OUTPUT_TXT)
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report[:800])
        print(f"  Saved: {txt_path}")
    except Exception as e:
        print(f"  Could not save summary: {e}")


def save_inline_comments(comments: list[dict], output_dir: str = ".") -> None:
    path = os.path.join(output_dir, OUTPUT_INLINE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(comments, f, indent=2)
        print(f"  Saved: {path}  ({len(comments)} inline comments)")
    except Exception as e:
        print(f"  Could not save inline-comments.json: {e}")


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    api_key = get_api_key()

    for required in ["checkov-output.json", "infracost-output.json"]:
        if not os.path.exists(required):
            print(f"ERROR: {required} not found.")
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
            breakdown_count = len(p.get("breakdown", {}).get("resources", []))
            diff_count      = len(p.get("diff", {}).get("resources", []))
            print(f"  project[{i}] breakdown resources: {breakdown_count}")
            print(f"  project[{i}] diff     resources: {diff_count}")

    print("> Loading Terraform source files ...")
    tf_sources = load_terraform_sources()
    print(f"  Terraform source: {len(tf_sources)} chars loaded")

    if not checkov_data:
        print("ERROR: Failed to parse checkov-output.json")
        sys.exit(1)
    if not infracost_data:
        print("ERROR: Failed to parse infracost-output.json")
        sys.exit(1)

    plan_text      = tf_sources
    checkov_text   = extract_checkov_text(checkov_data)
    infracost_text = extract_infracost_text(infracost_data)

    prompt = build_prompt(plan_text, checkov_text, infracost_text)
    report = ask_claude(prompt, api_key)

    print("\n> Saving reports ...")
    save_report(report)

    print("\n> Building inline comments ...")
    inline_comments = build_inline_comments(checkov_data, tf_sources)
    save_inline_comments(inline_comments)

    print("\nDone.")
    print(f"  {OUTPUT_MD}      <- PR summary comment")
    print(f"  {OUTPUT_JSON}    <- workflow artifact")
    print(f"  {OUTPUT_TXT}     <- notification snippet")
    print(f"  {OUTPUT_INLINE}  <- Files changed tab comments")


if __name__ == "__main__":
    main()