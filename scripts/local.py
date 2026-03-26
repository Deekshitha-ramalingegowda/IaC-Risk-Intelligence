#!/usr/bin/env python3

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

try:
    from google import genai
except ImportError:
    print("google-genai not installed.")
    print("Run: pip install google-genai")
    sys.exit(1)

CHECKOV_JSON = "checkov-output.json"
INFRACOST_JSON = "infracost-output.json"

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

    print(f"Failed to parse {filename}")
    return None


def get_file_info(filename):
    try:
        size_kb = os.path.getsize(filename) / 1024
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            lines = len(f.readlines())
        return round(size_kb, 2), lines
    except:
        return 0, 0


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set")
        print("Get key: https://aistudio.google.com/app/apikey")
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

   BEFORE MERGE (Address critical blockers):
   [List items that must be done before merge]

   WEEK 1 AFTER MERGE (Quick wins):
   - [Delete unused EBS volumes: saves $XX/month, 1 hour effort]
   - [Fix open SSH access: 10 minutes, zero downtime]

   WEEK 2-3 (Cost optimization):
   - [RDS downsizing: saves $XXX/month, 8 hours effort, 15-30 min downtime]

   WEEK 4 (Architectural improvements):
   - [Consider Reserved Instances if workload is stable]

7. PR MERGE DECISION SUMMARY:
   Should this PR be merged? YES / NO / CONDITIONAL

   If CONDITIONAL, list the specific conditions and timeline.

   If NO, explain which critical issues must be fixed first.

   If YES, what should the team focus on in the next 30 days?

Format as a clear, concise executive report suitable for engineering leadership/team leads to make a merge decision."""


def ask_gemini(prompt, api_key, analysis_type="security"):
    print(f"\n> Querying Gemini for {analysis_type} analysis...\n")

    client = genai.Client(api_key=api_key)

    for model in MODELS:
        try:
            print(f"Trying {model}")
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0.1, "max_output_tokens": 1500},
            )

            if response.text:
                return response.text.strip()

        except Exception as e:
            print(f"Failed: {e}")

    return "Gemini analysis failed."


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

def generate_executive_summary(sec, cost, api_key):

    prompt = build_executive_summary_prompt(sec, cost)
    return ask_gemini(prompt, api_key, "Executive Summary")


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():

    print("\n========= IaC Risk Intelligence =========\n")

    api_key = get_gemini_key()

    checkov_data = run_checkov()
    infracost_data = run_infracost()

    security_analysis = analyze_security_deep(checkov_data, api_key)
    cost_analysis = analyze_cost_deep(infracost_data, api_key)

    executive_summary = generate_executive_summary(
        security_analysis,
        cost_analysis,
        api_key,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_file = f"iac_audit_report_{timestamp}.md"

---

*Report generated by Infrastructure Analysis Tool (Checkov + Infracost + Gemini)*
"""

    try:
        with open(md_filename, 'w', encoding='utf-8') as f:
            f.write(md_content)
        print(f"\n✓ Markdown report saved: {md_filename}")
    except Exception as e:
        print(f"\n⚠ Failed to save markdown report: {e}")

    # Save as JSON (for artifacts)
    json_filename = f"{output_dir}/infrastructure-analysis-report.json"
    json_content = {
        "timestamp": datetime.now().isoformat(),
        "analyses": {
            "executive_summary": executive_summary,
            "security_analysis": security_analysis,
            "cost_analysis": cost_analysis
        }
    }


EXECUTIVE SUMMARY:
{executive_summary[:500]}...

For full details, see:
- infrastructure-analysis-report.md (formatted report)
- infrastructure-analysis-report.json (complete data)

---
End of Summary
"""

    try:
        with open(txt_filename, 'w', encoding='utf-8') as f:
            f.write(txt_content)
        print(f"✓ Text summary saved: {txt_filename}")
    except Exception as e:
        print(f"⚠ Failed to save text summary: {e}")


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