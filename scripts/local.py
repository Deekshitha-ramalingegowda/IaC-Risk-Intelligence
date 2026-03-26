#!/usr/bin/env python3
"""
IaC Risk Intelligence - Infrastructure Analysis Script
Runs Checkov + Infracost, sends results to Gemini AI,
posts a structured PR comment AND inline file annotations via GitHub API.
"""

import os
import sys
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime

try:
    from google import genai
except ImportError:
    print("google-genai not installed. Run: pip install google-genai")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    sys.exit(1)

# ============================================================
# CONSTANTS
# ============================================================

CHECKOV_JSON       = "checkov-output.json"
INFRACOST_JSON     = "infracost-output.json"
REPORT_MD          = "infrastructure-analysis-report.md"   # must match workflow expectation
REPORT_JSON        = "infrastructure-analysis-report.json"
REPORT_SUMMARY_TXT = "infrastructure-analysis-summary.txt"

<<<<<<< Updated upstream
MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-pro",
]
=======
# ----------------------------
# EXTRACT DATA (TOKEN OPTIMIZED)
# ----------------------------
def extract_tfsec_issues(data):
    issues = []
    for r in data.get("results", {}).get("failed_checks", [])[:10]:  # limit
        issues.append({
            "rule": r.get("rule_id"),
            "desc": r.get("description"),
            "severity": r.get("severity"),
            "resource": r.get("resource")
        })
    return issues
>>>>>>> Stashed changes

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def load_json_file(filename):
    encodings = ["utf-8-sig", "utf-16", "utf-8", "latin-1"]
    for enc in encodings:
        try:
            with open(filename, "r", encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    print(f"⚠ Failed to parse {filename}")
    return None


def get_file_info(filename):
    try:
        size_kb = os.path.getsize(filename) / 1024
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            lines = len(f.readlines())
        return round(size_kb, 2), lines
    except Exception:
        return 0, 0


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("❌ GEMINI_API_KEY not set")
        sys.exit(1)
    return key


# ============================================================================
# DATA EXTRACTION
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
        loc = file_path
        if len(line_range) == 2:
            loc += f":{line_range[0]}-{line_range[1]}"
        lines.append(f"[{check_id}] {resource}  ({loc})")
        lines.append(f"  Rule: {check_name}")
        lines.append("")
    return "\n".join(lines)


def _safe_float(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


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
                monthly = _safe_float(resource.get("monthlyCost"))
                if monthly == 0:
                    monthly = _safe_float(resource.get("hourlyCost")) * 730
                resource_costs.append((monthly, name, rtype))
    seen: dict = {}
    for entry in resource_costs:
        monthly, name, *_ = entry
        if name not in seen or monthly > seen[name][0]:
            seen[name] = entry
    resource_costs = sorted(seen.values(), reverse=True)
    for monthly, name, rtype in resource_costs[:10]:
        label    = f"{name} ({rtype})" if rtype else name
        cost_str = f"${monthly:.2f}/mo" if monthly > 0 else "$0.00/mo (unpriced)"
        lines.append(f"{label}: {cost_str}")
    return "\n".join(lines)


# ============================================================================
# SLIM GEMINI PROMPT  — two sections only, minimal tokens
# ============================================================================

ANALYSIS_PROMPT = """\
You are a cloud infrastructure reviewer. Analyze the Terraform changes below.

Output EXACTLY two sections, nothing else — no introduction, no conclusion, no markdown headers outside what is shown.

TERRAFORM PLAN
{plan}

CHECKOV RESULTS
## Security Issues
For each Checkov failed check, one line per issue:
[SEVERITY] check_id | resource | file:line | one-sentence fix

## Cost Impact
For each resource with a cost concern, one line:
resource_name | instance_type_or_config | estimated $/mo | one-sentence fix
End the section with one summary line: TOTAL ESTIMATED: $X/mo

Rules:
- If a section has no items write: (none)
- Maximum 2 sentences per line, no bullet sub-items
- Reference exact file and line number from the Terraform source

TERRAFORM SOURCE
{plan}

CHECKOV FAILED CHECKS
{security}

INFRACOST DIFF
{cost}

IMPORTANT: If resources show "$0.00 (unpriced)", Infracost could not fetch live prices.
Use the Terraform source above to estimate costs based on AWS on-demand pricing for
us-east-1 and mark estimates with "(estimated)". Never write "None" for Cost Impact
if the resource is clearly billable.
"""

1. INFRASTRUCTURE HEALTH SCORECARD:
   Overall Grade: [A-F with clear reasoning]
   - What's the most critical issue preventing an A grade?

def build_prompt(plan_text, checkov_text, infracost_text):
    # Only feed the modules/ec2.tf source to keep tokens minimal
    ec2_lines = []
    in_ec2 = False
    for line in plan_text.splitlines():
        if "modules/ec2.tf" in line or "modules\\ec2.tf" in line:
            in_ec2 = True
        elif line.startswith("# -- ") and in_ec2:
            in_ec2 = False
        if in_ec2:
            ec2_lines.append(line)
    ec2_source = "\n".join(ec2_lines) if ec2_lines else plan_text[:4000]

    return ANALYSIS_PROMPT.format(
        plan=ec2_source,
        security=checkov_text,
        cost=infracost_text,
    )

   Cost Efficiency Grade: [A-F]
   - Is the infrastructure cost appropriate for what it does?

   Compliance Status: [GREEN/YELLOW/RED]
   - Any compliance violations?

2. PR MERGE DECISION RECOMMENDATION:
   ✓ APPROVE - Infrastructure is secure and cost-appropriate
   ⚠ APPROVE WITH CONDITIONS - Fix these 2-3 items before/after merge:
      1. [Issue with timeline]
      2. [Issue with timeline]
   ✗ REQUEST CHANGES - Block merge until these critical items are fixed:
      1. [Critical issue with why it blocks]
      2. [Critical issue]

3. KEY METRICS & BUSINESS IMPACT:
   Security Risks:
   - Critical issues: [N] (what they are)
   - High issues: [N] (what they are)
   - Total effort to remediate: [X] hours
   - Timeline: Can be fixed in [X] weeks

   Cost Analysis:
   - Monthly cost: $XXX (is this high/appropriate?)
   - Savings potential: $XXX/month ([X]% reduction)
   - Payback period: [X] weeks to break even on optimization effort
   - Annual impact: $XXX/year in savings if optimized

4. CRITICAL ITEMS FOR PR MERGE (if any):
   [For each critical blocker, state exactly why it prevents merge]

   Example:
   - Open SSH access (port 22 to 0.0.0.0/0): ANY IP can gain shell access
     Status: CRITICAL BLOCKER - Must be fixed before merge
     Fix effort: 10 minutes (add restrict_security_group_rule)
     Recommended action: Request changes, fix, then approve

   - Database with no encryption: Customer data vulnerable to eavesdropping
     Status: CRITICAL BLOCKER - Must be fixed before merge
     Fix effort: 2-3 hours (create encrypted snapshot, restore)

5. ITEMS THAT CAN BE FIXED POST-MERGE (optional):
   [Non-blocking improvements]

   Example:
   - RDS downsizing from db.r5.2xlarge to db.r5.xlarge
     Savings: $525.80/month
     Effort: 8 hours (testing required)
     Timeline: Can be done in Week 2
     Risk: 15-30 min downtime for RDS failover
     Recommendation: Fix after merge during maintenance window

6. 30-DAY IMPLEMENTATION ROADMAP:

EXECUTIVE_SYSTEM = """
You are a CTO reviewing an infrastructure pull request.
Always respond with:

## ✅ / ❌ Merge Recommendation
## 📋 Overall Grade
## 🔐 Security Grade
## 💰 Cost Grade
## 🗓️ 30-Day Roadmap (numbered steps)

Be direct. Start with the merge decision.
"""


def build_security_prompt(checkov_data):
    failed = checkov_data.get("results", {}).get("failed_checks", [])
    summary = f"Total failed checks: {len(failed)}\n\n"
    for check in failed[:30]:
        summary += (
            f"- **{check.get('check_id')}** | "
            f"`{check.get('resource')}` | "
            f"{check.get('check_name')} | "
            f"File: `{check.get('repo_file_path', 'unknown')}` "
            f"Line: {check.get('file_line_range', ['?', '?'])[0]}\n"
        )
    return f"Analyze these Terraform security findings:\n\n{summary}"


def build_cost_prompt(infracost_data):
    if not infracost_data:
        return "No cost data available. Note that NAT Gateways cost ~$36/month and VPC endpoints are a cheaper alternative."
    total = float(infracost_data.get("totalMonthlyCost", 0))
    projects = json.dumps(infracost_data.get("projects", [])[:3], indent=2)
    return f"Monthly Cost: ${total}\n\nProject breakdown:\n{projects}"


def build_executive_prompt(sec, cost):
    return f"SECURITY ANALYSIS:\n{sec}\n\nCOST ANALYSIS:\n{cost}"


# ============================================================
# GEMINI CALL
# ============================================================

def ask_gemini(system_prompt, user_prompt, api_key, name):
    print(f"\n🧠 Gemini Analysis → {name}")
    client = genai.Client(api_key=api_key)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    for model in MODELS:
        try:
            print(f"  Trying {model}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"temperature": 0.1, "max_output_tokens": 1500},
            )
            if response.text:
                print(f"  ✓ Success with {model}")
                return response.text.strip()
        except Exception as e:
            print(f"failed > {str(e)[:80]}...")

    print(f"\n All models failed for {analysis_type} analysis.")
    return f"Failed to get {analysis_type} analysis from Gemini."


# ============================================================================
# INLINE COMMENTS  — only the two issues in ec2.tf
# ============================================================================

# Exactly two targeted rules for ec2.tf only.
# Each entry: (file_glob, line_regex, severity, check_id, title, fix)
EC2_INLINE_RULES = [
    (
        "ec2.tf",
        r'monitoring\s*=\s*false',
        "HIGH",
        "CKV_AWS_126",
        "Detailed CloudWatch monitoring is disabled",
        (
            "Change monitoring = false to monitoring = true.\n\n"
            "Without detailed monitoring, CloudWatch only collects metrics every 5 minutes "
            "instead of every 1 minute, making it impossible to detect short-lived CPU spikes "
            "or respond quickly to incidents.\n\n"
            "Fix:\n```hcl\nmonitoring = true\n```"
        ),
    ),
    (
        "ec2.tf",
        r'instance_type\s*=\s*var\.ec2_instance_type',
        "COST",
        "COST_EC2_OVERSIZE",
        "EC2 instance type m5.2xlarge is oversized",
        (
            "Default ec2_instance_type is m5.2xlarge (~$277/mo). "
            "Downsize to m5.large (~$70/mo) or t3.large (~$60/mo) after load testing.\n\n"
            "Fix in terraform/variables.tf:\n"
            "```hcl\nvariable \"ec2_instance_type\" {\n"
            "  default = \"m5.large\"\n}\n```\n\n"
            "Or override in terraform.tfvars:\n"
            "```hcl\nec2_instance_type = \"m5.large\"\n```"
        ),
    ),
]


def build_inline_comments(tf_sources_raw):
    """
    Produce { path, line, body } dicts for GitHub's pulls.createReviewComment API.
    Only targets the two known issues in terraform/modules/ec2.tf.
    """
    comments = []
    seen = set()  # (path, line, key) - prevents duplicate comments on same line

    for search_dir in ["terraform", "."]:
        base = Path(search_dir)
        if not base.is_dir():
            continue
        tf_files = sorted(base.rglob("*.tf"))
        if not tf_files:
            continue

        for tf_path in tf_files:
            filename = tf_path.name  # e.g. "ec2.tf"
            try:
                rel_path   = str(tf_path).lstrip("./")
                file_lines = tf_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for file_glob, line_regex, severity, check_id, title, fix in EC2_INLINE_RULES:
                if filename != file_glob:
                    continue
                for lineno, raw_line in enumerate(file_lines, start=1):
                    stripped = raw_line.strip()
                    if stripped.startswith("#"):
                        continue
                    if re.search(line_regex, stripped, re.IGNORECASE):
                        dedup_key = (rel_path, lineno, check_id)
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        body = (
                            f"[{severity}] {check_id} — {title}\n\n"
                            f"File: {rel_path}, line {lineno}\n\n"
                            f"{fix}"
                        )
                        comments.append({"path": rel_path, "line": lineno, "body": body})
        break  # stop after first directory that has .tf files

    return comments


def save_inline_comments(comments, output_dir="."):
    path = f"{output_dir}/inline-comments.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(comments, f, indent=2)
        print(f"  Saved: {path}  ({len(comments)} inline comments)")
    except Exception as e:
        print(f"  Could not save inline-comments.json: {e}")

    comments = []
    for check in failed_checks:
        repo_path  = check.get("repo_file_path", "").lstrip("/")
        line_range = check.get("file_line_range", [1, 1])
        start_line = line_range[0] if line_range else 1
        check_id   = check.get("check_id", "")
        check_name = check.get("check_name", "")
        resource   = check.get("resource", "")
        guideline  = check.get("guideline", "")

        # Normalise path — checkov sometimes prefixes with terraform/
        candidate_paths = [
            repo_path,
            f"terraform/{Path(repo_path).name}",
            Path(repo_path).name,
        ]
        patch      = ""
        final_path = repo_path
        for p in candidate_paths:
            if p in patch_map:
                patch      = patch_map[p]
                final_path = p
                break

        position = patch_line_to_position(patch, start_line)
        if position is None:
            # Line not in diff — skip inline comment for this check
            continue

        body = (
            f"### 🔐 Security Finding: `{check_id}`\n"
            f"**Resource:** `{resource}`\n"
            f"**Issue:** {check_name}\n\n"
            f"**Risk:** This configuration may expose your infrastructure to unauthorized access or compliance violations.\n\n"
            f"**Suggested Fix:**\n"
        )

        # Attach specific fix hints for common checks
        if "encrypted" in check_name.lower():
            body += (
                "```hcl\n"
                "root_block_device {\n"
                "  encrypted = true\n"
                "}\n"
                "```\n"
            )
        elif "ssh" in check_name.lower() or "0.0.0.0" in check_name.lower():
            body += (
                "```hcl\n"
                "ingress {\n"
                '  description = "SSH from trusted IP only"\n'
                "  from_port   = 22\n"
                "  to_port     = 22\n"
                '  protocol    = "tcp"\n'
                '  cidr_blocks = ["203.0.113.0/24"]  # Replace with your VPN/office IP\n'
                "}\n"
                "```\n"
            )
        elif "monitoring" in check_name.lower():
            body += (
                "```hcl\n"
                "resource \"aws_instance\" \"app\" {\n"
                "  monitoring = true\n"
                "}\n"
                "```\n"
            )
        elif "imds" in check_name.lower() or "metadata" in check_name.lower():
            body += (
                "```hcl\n"
                "metadata_options {\n"
                '  http_tokens = "required"  # Enforce IMDSv2\n'
                "}\n"
                "```\n"
            )
        else:
            body += f"Review Checkov guideline: {guideline}\n" if guideline else "Apply the recommended Terraform fix.\n"

        comments.append({
            "path":     final_path,
            "position": position,
            "body":     body,
        })

    if not comments:
        print("⚠ No inline comments matched diff positions")
        return

    # Create a single PR Review with all inline comments
    url     = f"https://api.github.com/repos/{gh['repo']}/pulls/{gh['pr_number']}/reviews"
    headers = {
        "Authorization": f"Bearer {gh['token']}",
        "Accept":        "application/vnd.github+json",
    }
    payload = {
        "commit_id": gh["commit_sha"],
        "body":      "## 🤖 Automated Security Review\nInline annotations from Checkov + Gemini AI analysis. See the PR comment below for the full report.",
        "event":     "COMMENT",
        "comments":  comments,
    }
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        print(f"✓ Posted {len(comments)} inline review comment(s)")
    else:
        print(f"⚠ Inline review failed: {resp.status_code} — {resp.text[:300]}")


# ============================================================
# PR COMMENT (Summary Report)
# ============================================================

def build_pr_comment(security_analysis, cost_analysis, executive_summary, checkov_data, infracost_data):
    failed  = checkov_data.get("results", {}).get("failed_checks", [])
    passed  = checkov_data.get("results", {}).get("passed_checks", [])
    total_cost = float(infracost_data.get("totalMonthlyCost", 0)) if infracost_data else 0

    # Build per-finding table rows
    finding_rows = ""
    for check in failed[:15]:
        check_id   = check.get("check_id", "")
        resource   = check.get("resource", "")
        check_name = check.get("check_name", "")
        repo_path  = check.get("repo_file_path", "")
        line_range = check.get("file_line_range", ["-", "-"])
        start_line = line_range[0] if line_range else "-"
        finding_rows += f"| `{check_id}` | `{resource}` | {check_name} | `{repo_path}:{start_line}` |\n"

    comment = f"""## 🛡️ Infrastructure Analysis & Risk Intelligence Report

> Generated by Gemini AI + Checkov + Infracost on {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}

---

## 📊 Summary Dashboard

| Metric | Value |
|---|---|
| 🔴 Security Findings | `{len(failed)}` failed checks |
| ✅ Passed Checks | `{len(passed)}` |
| 💰 Monthly Cost Estimate | `${total_cost:.2f}` |

---

## 🔐 Security Findings

| Check ID | Resource | Issue | File:Line |
|---|---|---|---|
{finding_rows if finding_rows else "| — | — | No findings | — |"}

---

## 🔍 Detailed Security Analysis

{security_analysis}

---

## 💸 Cost Analysis

{cost_analysis}

---

## 🏢 Executive Summary & Merge Decision

{executive_summary}


All raw reports (`checkov-output.json`, `infracost-output.json`, full markdown report) are available in the **Actions → Artifacts** section of this workflow run.

</details>

---
*🤖 Automated analysis — review all suggestions before applying. Inline code annotations have been added directly to the changed lines above.*
"""
    return comment


def post_pr_comment(gh, comment_body):
    if not gh["token"] or not gh["repo"] or not gh["pr_number"]:
        print("⚠ GitHub env vars missing — skipping PR comment")
        return
    if gh["event_name"] != "pull_request":
        print("⚠ Not a pull_request event — skipping PR comment")
        return

    print("> Loading Terraform source files ...")
    tf_sources = load_terraform_sources()

    if not valid:
        print(f"Error: {msg}")
        print("\nFirst, run the security and cost analysis:")
        print("  1. Run Checkov: checkov -d . --framework terraform -o json")
        print("  2. Run Infracost: infracost breakdown -p . --format json")
        sys.exit(1)
    if not infracost_data:
        print("Error: Failed to parse infracost-output.json")
        sys.exit(1)

    checkov_text   = extract_checkov_text(checkov_data)
    infracost_text = extract_infracost_text(infracost_data)

    prompt = build_prompt(tf_sources, checkov_text, infracost_text)
    report = ask_gemini(prompt, api_key)

    print("\n> Saving report ...")
    save_report(report)

    print("\n> Building inline comments ...")
    inline_comments = build_inline_comments(tf_sources)
    save_inline_comments(inline_comments)

    print("\nDone.")
    print("  infrastructure-analysis-report.md  <- PR summary comment (2 sections only)")
    print("  infrastructure-analysis-report.json <- artifact")
    print("  inline-comments.json               <- Files Changed tab annotations")


if __name__ == "__main__":
    main()