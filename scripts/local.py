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

MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-pro",
]

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


def get_github_env():
    """Collect all GitHub context variables needed for PR comments and annotations."""
    return {
        "token":      os.getenv("GITHUB_TOKEN", ""),
        "repo":       os.getenv("GITHUB_REPOSITORY", ""),       # owner/repo
        "pr_number":  os.getenv("PR_NUMBER", ""),
        "commit_sha": os.getenv("GITHUB_SHA", ""),
        "event_name": os.getenv("GITHUB_EVENT_NAME", ""),
    }


# ============================================================
# CHECKOV
# ============================================================

def run_checkov():
    print("\n🔍 Running Checkov...\n")
    cmd = [
        "checkov", "-d", "terraform/",
        "--framework", "terraform",
        "-o", "json",
        "--soft-fail",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    with open(CHECKOV_JSON, "w", encoding="utf-8") as f:
        f.write(result.stdout)
    try:
        data = json.loads(result.stdout)
        failed = data.get("results", {}).get("failed_checks", [])
        print(f"✓ Checkov complete: {len(failed)} failed checks")
        return data
    except Exception:
        print("⚠ Checkov JSON parse failed — using empty result")
        return {"results": {"failed_checks": [], "passed_checks": []}}


# ============================================================
# INFRACOST
# ============================================================

def run_infracost():
    print("\n💰 Running Infracost...\n")
    if not os.getenv("INFRACOST_API_KEY"):
        print("⚠ INFRACOST_API_KEY missing — skipping cost analysis")
        return None
    cmd = ["infracost", "breakdown", "--path", "terraform/", "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("⚠ Infracost failed")
        return None
    with open(INFRACOST_JSON, "w", encoding="utf-8") as f:
        f.write(result.stdout)
    try:
        return json.loads(result.stdout)
    except Exception:
        return None


# ============================================================
# PROMPTS
# ============================================================

SECURITY_SYSTEM = """
You are a Cloud Security Architect reviewing Terraform infrastructure.
Always respond in structured Markdown with these exact sections:

## 🔴 Critical Risks
## ⚠️ Attack Scenarios
## 🛠️ Exact Terraform Fixes
## 📊 Risk Grading (A–F)
## 🗺️ Remediation Roadmap

For each finding include:
- **Finding**: short title
- **Security group / Resource**: resource name
- **Risk**: impact description
- **Root Cause**: what caused it
- **Solution**: how to fix it
- **Steps to Fix**: numbered list
- **Terraform Fix Example**: fenced code block
"""

COST_SYSTEM = """
You are a FinOps Architect reviewing Terraform infrastructure costs.
Always respond in structured Markdown with these exact sections:

## 💸 Oversized Resources
## 💡 Cost Savings Opportunities
## 📉 Downsizing Suggestions
## 💰 Estimated Savings
## 🏷️ Cost Efficiency Grade

For each resource include a table:
| Resource | Previous Cost | New Cost | Increase | Risk | Solution |

Then provide Terraform Fix Examples as fenced code blocks.
"""

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
                model=model,
                contents=full_prompt,
                config={"temperature": 0.2, "max_output_tokens": 8192},
            )
            if response.text:
                print(f"  ✓ Success with {model}")
                return response.text.strip()
        except Exception as e:
            print(f"  ✗ Failed: {e}")
    return "Gemini analysis failed — check API key and quota."


# ============================================================
# GITHUB INLINE COMMENTS (Review Annotations)
# ============================================================

def get_pr_diff_files(gh):
    """Return list of files changed in the PR with their patch hunks."""
    if not gh["token"] or not gh["repo"] or not gh["pr_number"]:
        return []
    url = f"https://api.github.com/repos/{gh['repo']}/pulls/{gh['pr_number']}/files"
    headers = {
        "Authorization": f"Bearer {gh['token']}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"⚠ Could not fetch PR files: {resp.status_code}")
        return []
    return resp.json()


def patch_line_to_position(patch, target_line):
    """
    Convert an actual file line number to a GitHub diff position index.
    GitHub's review comment API uses 'position' = line index within the patch hunk.
    Returns None if the line isn't in the diff.
    """
    if not patch:
        return None
    position = 0
    current_line = 0
    for raw_line in patch.split("\n"):
        if raw_line.startswith("@@"):
            # Extract the starting line from the hunk header e.g. @@ -0,0 +10,20 @@
            match = re.search(r"\+(\d+)", raw_line)
            if match:
                current_line = int(match.group(1)) - 1
            position += 1
        elif raw_line.startswith("+"):
            current_line += 1
            position += 1
            if current_line == target_line:
                return position
        elif raw_line.startswith("-"):
            position += 1
        else:
            current_line += 1
            position += 1
    return None


def post_inline_review_comments(gh, checkov_data, security_analysis):
    """
    Post GitHub Pull Request Review with inline comments on the exact changed lines.
    Each Checkov failed check gets an annotation on the offending line in the diff.
    """
    if not gh["token"] or not gh["repo"] or not gh["pr_number"] or not gh["commit_sha"]:
        print("⚠ GitHub env vars missing — skipping inline comments")
        return

    failed_checks = checkov_data.get("results", {}).get("failed_checks", [])
    if not failed_checks:
        print("✓ No failed checks — no inline comments needed")
        return

    pr_files = get_pr_diff_files(gh)
    # Build a map: filename → patch
    patch_map = {f["filename"]: f.get("patch", "") for f in pr_files}

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

---

<details>
<summary>📁 Artifacts</summary>

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

    url = f"https://api.github.com/repos/{gh['repo']}/issues/{gh['pr_number']}/comments"
    headers = {
        "Authorization": f"Bearer {gh['token']}",
        "Accept":        "application/vnd.github+json",
    }
    resp = requests.post(url, headers=headers, json={"body": comment_body})
    if resp.status_code in (200, 201):
        print("✓ PR comment posted successfully")
    else:
        print(f"⚠ PR comment failed: {resp.status_code} — {resp.text[:300]}")


# ============================================================
# REPORT FILES
# ============================================================

def write_reports(security_analysis, cost_analysis, executive_summary, checkov_data, infracost_data):
    failed     = checkov_data.get("results", {}).get("failed_checks", [])
    passed     = checkov_data.get("results", {}).get("passed_checks", [])
    total_cost = float(infracost_data.get("totalMonthlyCost", 0)) if infracost_data else 0

    # --- Markdown report (must be named infrastructure-analysis-report.md) ---
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("# IaC Risk Intelligence Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n")
        f.write(f"**Security Findings:** {len(failed)} failed / {len(passed)} passed\n\n")
        f.write(f"**Monthly Cost Estimate:** ${total_cost:.2f}\n\n")
        f.write("---\n\n")
        f.write("## Security Analysis\n\n")
        f.write(security_analysis)
        f.write("\n\n---\n\n")
        f.write("## Cost Analysis\n\n")
        f.write(cost_analysis)
        f.write("\n\n---\n\n")
        f.write("## Executive Summary\n\n")
        f.write(executive_summary)
    print(f"✓ Markdown report: {REPORT_MD}")

    # --- JSON report ---
    report_data = {
        "timestamp":          datetime.now().isoformat(),
        "security_findings":  len(failed),
        "passed_checks":      len(passed),
        "monthly_cost":       total_cost,
        "security_analysis":  security_analysis,
        "cost_analysis":      cost_analysis,
        "executive_summary":  executive_summary,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    print(f"✓ JSON report: {REPORT_JSON}")

    # --- Summary text ---
    with open(REPORT_SUMMARY_TXT, "w", encoding="utf-8") as f:
        f.write(f"Security Findings: {len(failed)}\n")
        f.write(f"Passed Checks: {len(passed)}\n")
        f.write(f"Monthly Cost: ${total_cost:.2f}\n")
    print(f"✓ Summary: {REPORT_SUMMARY_TXT}")


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    print("\n========= IaC Risk Intelligence Pipeline =========\n")

    api_key = get_gemini_key()
    gh      = get_github_env()

    # --- Run scanners ---
    checkov_data   = run_checkov()
    infracost_data = run_infracost()

    # Ensure checkov_data is always a dict
    if not checkov_data:
        checkov_data = {"results": {"failed_checks": [], "passed_checks": []}}
    if not infracost_data:
        infracost_data = {"totalMonthlyCost": 0, "projects": []}

    # --- AI Analysis ---
    security_analysis = ask_gemini(
        SECURITY_SYSTEM,
        build_security_prompt(checkov_data),
        api_key,
        "Security Deep Dive",
    )
    cost_analysis = ask_gemini(
        COST_SYSTEM,
        build_cost_prompt(infracost_data),
        api_key,
        "Cost Analysis",
    )
    executive_summary = ask_gemini(
        EXECUTIVE_SYSTEM,
        build_executive_prompt(security_analysis, cost_analysis),
        api_key,
        "Executive Summary",
    )

    # --- Write report files ---
    write_reports(security_analysis, cost_analysis, executive_summary, checkov_data, infracost_data)

    # --- Post inline review comments on changed lines ---
    post_inline_review_comments(gh, checkov_data, security_analysis)

    # --- Post full PR comment ---
    comment_body = build_pr_comment(
        security_analysis, cost_analysis, executive_summary, checkov_data, infracost_data
    )
    post_pr_comment(gh, comment_body)

    print("\n✅ Pipeline completed successfully.\n")


if __name__ == "__main__":
    main()