#!/usr/bin/env python3

import os
import sys
import json
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

def load_json_file(filename):
    """Load JSON file, trying multiple encodings."""
    for encoding in ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-8', 'latin-1']:
        try:
            with open(filename, 'r', encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    print(f"Error: Could not parse {filename}")
    return None


def load_terraform_sources(terraform_dir="terraform"):
    """
    Load all .tf files and return as a single numbered string.
    Falls back to current directory if terraform/ is absent.
    """
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
                parts.append(f"\n# ── {tf_path} ──\n{numbered}")
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

def extract_checkov_text(checkov_data):
    """
    Convert Checkov JSON into compact plain-text Checkov results.
    Includes check ID, resource, file:line, rule name, and code snippet.
    """
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
            snippet = "\n".join(
                f"  {ln}: {code.rstrip()}"
                for ln, code in code_block[:10]
            )
            lines.append(f"  Code:\n{snippet}")

        lines.append("")

    return "\n".join(lines)


def _safe_float(value):
    """Safely convert a value to float, returning 0.0 on failure."""
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def _extract_resource_cost(resource):
    """
    Extract monthly cost from a single Infracost resource dict.
    Infracost stores costs in costComponents and subresources.
    New resources have monthlyCost on the resource itself OR only in components.
    Returns (monthly_total, components_text_list).
    """
    monthly = 0.0
    components = []

    # Top-level monthlyCost on the resource (present in some versions)
    monthly += _safe_float(resource.get("monthlyCost"))

    for cost in resource.get("costComponents", []):
        c = _safe_float(cost.get("monthlyCost"))
        # Also check hourlyCost * 730 as fallback when monthlyCost is absent
        if c == 0:
            c = _safe_float(cost.get("hourlyCost")) * 730
        monthly += c
        desc = cost.get("description", "")
        qty  = cost.get("monthlyQuantity") or cost.get("quantity") or ""
        unit = cost.get("unit", "")
        if desc:
            components.append(
                f"    * {desc}: {qty} {unit} = ${c:.2f}/mo"
            )

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
    """
    Convert Infracost JSON into compact plain-text cost breakdown.
    Handles both 'breakdown' (all resources) and 'diff' (changed resources),
    and correctly processes new resources that have no prior baseline.
    """
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
            section = project.get(section_key, {})
            resources = section.get("resources", [])

            if not resources:
                resources = project.get("resources", [])

            for resource in resources:
                name  = resource.get("name", "unknown")
                rtype = resource.get("resourceType", "")

                monthly, components = _extract_resource_cost(resource)

                # Last resort: if still 0, check resource-level hourlyCost
                if monthly == 0:
                    monthly = _safe_float(resource.get("hourlyCost")) * 730

                # Include ALL resources (even $0) so Gemini can see them
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
        lines.append("⚠ All resources show $0.00 — Infracost could not price these resources.")
        lines.append("  Possible causes:")
        lines.append("  1. INFRACOST_API_KEY not set or invalid.")
        lines.append("  2. Resources use data sources / variables Infracost cannot resolve.")
        lines.append("  3. Resources are free-tier or not yet supported.")
        lines.append("")
        lines.append("Resources found (unpriced):")

    for monthly, name, rtype, components, proj, section in resource_costs[:15]:
        label = f"{name} ({rtype})" if rtype else name
        cost_str = f"${monthly:.2f}/mo" if monthly > 0 else "$0.00/mo (unpriced)"
        lines.append(f"{label}: {cost_str}")
        lines.extend(components[:4])
        lines.append("")

    return "\n".join(lines)


def extract_terraform_plan_text(tf_sources):
    """
    Use the raw .tf source as the 'plan' since terraform plan output
    is not available in this workflow.
    """
    if not tf_sources:
        return "No Terraform source available."
    return tf_sources[:12000]


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
**Root Cause:** <why this exists in the code — include resource name and file:line>
**Solution:** <what to do>
**Steps to Fix:**
1. <step>
2. <step>
3. <step>
**Terraform Fix Example:**
```hcl
<corrected resource block — only the changed attributes>
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

IMPORTANT: If resources show "$0.00 (unpriced)", Infracost could not fetch live prices
(missing API key or unsupported resource). In that case, use the Terraform source above
to estimate costs based on well-known AWS on-demand pricing for us-east-1, and clearly
mark estimates with "(estimated)". Still produce the Cost Impact section with your best
estimate rather than writing "None" or skipping it.
"""


def build_prompt(plan_text, checkov_text, infracost_text):
    return ANALYSIS_PROMPT.format(
        plan=plan_text,
        security=checkov_text,
        cost=infracost_text,
    )

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


SEVERITY_MAP = {
    "CKV_AWS_8":   (" CRITICAL", "Root volume is unencrypted. Fix: add `encrypted = true` inside `root_block_device`."),
    "CKV_AWS_135": (" CRITICAL", "EBS volume is unencrypted. Fix: add `encrypted = true`."),
    "CKV_AWS_3":   (" CRITICAL", "S3 bucket allows public access. Fix: set all `block_public_*` to `true`."),
    "CKV_AWS_19":  (" CRITICAL", "S3 bucket has no server-side encryption. Fix: add `aws_s3_bucket_server_side_encryption_configuration`."),
    "CKV_AWS_17":  (" CRITICAL", "RDS instance is publicly accessible. Fix: `publicly_accessible = false`."),
    "CKV_AWS_16":  (" CRITICAL", "RDS storage is not encrypted. Fix: `storage_encrypted = true`."),
    "CKV_AWS_293": (" CRITICAL", "RDS has no backup retention. Fix: `backup_retention_period = 7`."),
    "CKV_AWS_161": (" CRITICAL", "RDS uses hardcoded password. Fix: remove `password`, add `manage_master_user_password = true`."),
    "CKV_AWS_25":  (" CRITICAL", "Security group allows unrestricted ingress. Fix: replace `0.0.0.0/0` with your VPN/app CIDR."),
    "CKV_AWS_24":  (" CRITICAL", "Security group allows SSH (port 22) from anywhere. Fix: `cidr_blocks = [\"10.0.0.0/8\"]`."),
    "CKV_AWS_23":  (" HIGH",     "Security group allows unrestricted egress. Fix: scope to specific CIDRs/ports."),
    "CKV_AWS_40":  (" CRITICAL", "IAM policy uses wildcard Action `*`. Fix: scope to minimum required actions."),
    "CKV_AWS_355": (" CRITICAL", "IAM policy uses wildcard Resource `*`. Fix: scope to specific ARNs."),
    "CKV2_AWS_5":  (" HIGH",     "Security group is not attached to any resource. Verify it is in use or remove it."),
    "CKV_AWS_79":  (" HIGH",     "EC2 instance metadata IMDSv2 not enforced. Fix: add `metadata_options { http_tokens = \"required\" }`."),
    "CKV_AWS_126": (" MEDIUM",   "EC2 detailed monitoring disabled. Fix: `monitoring = true`."),
}

COST_CHECKS = {
    # resource_type keyword → (label, suggestion)
    "m5.2xlarge":   (" COST",  "m5.2xlarge ≈ $277/mo. Consider t3.large (~$60/mo) or m5.large (~$70/mo) after benchmarking."),
    "m5.4xlarge":   (" COST",  "m5.4xlarge ≈ $553/mo. Consider m5.xlarge (~$138/mo) after benchmarking."),
    "r5.2xlarge":   (" COST",  "db.r5.2xlarge ≈ $700/mo. Consider db.t3.medium (~$60/mo) for dev or db.m5.large (~$140/mo) for prod."),
    "r5.4xlarge":   (" COST",  "db.r5.4xlarge ≈ $1,400/mo. Consider db.r5.xlarge (~$350/mo) after load testing."),
    "volume_size.*500": (" COST", "500 GB EBS volume ≈ $50/mo. Right-size to actual usage (typically 20–50 GB for OS)."),
    "volume_size.*1000":(" COST", "1,000 GB EBS volume ≈ $115/mo. Reduce to actual DB data size + 20% headroom."),
    "gp2":          (" COST",  "gp2 volume type is 20% more expensive than gp3 with lower baseline IOPS. Fix: `volume_type = \"gp3\"`."),
    "allocated_storage.*1000": (" COST", "1,000 GB allocated storage ≈ $115/mo. Reduce to actual need (e.g. 100 GB)."),
}


def build_inline_comments(checkov_data, tf_sources_raw):
    """
    Build a list of inline comment dicts ready for GitHub's
    pulls.createReviewComment API:
      { path, line, body }

    Sources:
    - Checkov failed_checks  → security comments (exact file + line from Checkov)
    - tf_sources_raw         → cost comments (scan for expensive patterns)
    """
    comments = []
    seen = set()

    failed = checkov_data.get("results", {}).get("failed_checks", []) if checkov_data else []

    for check in failed:
        check_id   = check.get("check_id", "")
        file_path  = check.get("file_path", "").lstrip("/")
        line_range = check.get("file_line_range", [])
        check_name = check.get("check_name", "")
        resource   = check.get("resource", "")

        if not file_path or not line_range:
            continue

        # GitHub inline comments attach to the last line of the block
        line = line_range[1] if len(line_range) == 2 else line_range[0]
        key  = (file_path, line, check_id)
        if key in seen:
            continue
        seen.add(key)

        severity, fix_hint = SEVERITY_MAP.get(
            check_id,
            ("🟡 MEDIUM", f"Review `{check_name}` for resource `{resource}`."),
        )

        body = (
            f"**{severity} — [{check_id}]** `{resource}`\n\n"
            f"> {fix_hint}"
        )
        comments.append({"path": file_path, "line": line, "body": body})

    import re

    for search_dir in ["terraform", "."]:
        base = Path(search_dir)
        if not base.is_dir():
            continue
        tf_files = sorted(base.rglob("*.tf"))
        if not tf_files:
            continue

        for tf_path in tf_files:
            try:
                rel_path = str(tf_path).lstrip("./")
                file_lines = tf_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for lineno, raw_line in enumerate(file_lines, start=1):
                stripped = raw_line.strip()
                for pattern, (label, hint) in COST_CHECKS.items():
                    if re.search(pattern, stripped):
                        key = (rel_path, lineno, pattern)
                        if key in seen:
                            continue
                        seen.add(key)
                        body = f"**{label}** — {hint}"
                        comments.append({"path": rel_path, "line": lineno, "body": body})
        break   # stop after first dir that has .tf files

    return comments


def save_inline_comments(comments, output_dir="."):
    path = f"{output_dir}/inline-comments.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(comments, f, indent=2)
        print(f"  Saved: {path}  ({len(comments)} inline comments)")
    except Exception as e:
        print(f"  Could not save inline-comments.json: {e}")

def save_report(report, output_dir="."):
    """Save the PR comment markdown and a JSON artifact."""

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
            json.dump(
                {"timestamp": datetime.now().isoformat(), "report": report},
                f, indent=2
            )
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


def main():
    api_key = get_gemini_key()

    # Validate input files
    for required in ["checkov-output.json", "infracost-output.json"]:
        if not os.path.exists(required):
            print(f"Error: {required} not found.")
            print("Run Checkov and Infracost before calling this script.")
            sys.exit(1)

    # Load inputs
    print("> Loading checkov-output.json ...")
    checkov_data = load_json_file("checkov-output.json")

    print("> Loading infracost-output.json ...")
    infracost_data = load_json_file("infracost-output.json")

    # Debug: show what Infracost actually returned
    if infracost_data:
        top_keys = list(infracost_data.keys())
        projects = infracost_data.get("projects", [])
        total    = infracost_data.get("totalMonthlyCost", "missing")
        print(f"  Infracost keys    : {top_keys}")
        print(f"  totalMonthlyCost  : {total}")
        print(f"  projects found    : {len(projects)}")
        for i, p in enumerate(projects[:3]):
            bdown = p.get("breakdown", {})
            diff  = p.get("diff", {})
            print(f"  project[{i}] breakdown resources: {len(bdown.get('resources', []))}")
            print(f"  project[{i}] diff     resources: {len(diff.get('resources', []))}")

    print("> Loading Terraform source files ...")
    tf_sources = load_terraform_sources()

    if not checkov_data:
        print("Error: Failed to parse checkov-output.json")
        sys.exit(1)

    if not infracost_data:
        print("Error: Failed to parse infracost-output.json")
        sys.exit(1)

    # Build plain-text inputs for the prompt
    plan_text      = extract_terraform_plan_text(tf_sources)
    checkov_text   = extract_checkov_text(checkov_data)
    infracost_text = extract_infracost_text(infracost_data)

    # Single Gemini call
    prompt = build_prompt(plan_text, checkov_text, infracost_text)
    report = ask_gemini(prompt, api_key)

    # Save
    print("\n> Saving reports ...")
    save_report(report)

    # Build and save inline comments for "Files changed" tab
    print("\n> Building inline comments ...")
    inline_comments = build_inline_comments(checkov_data, tf_sources)
    save_inline_comments(inline_comments)

    print("\nDone.")
    print("  infrastructure-analysis-report.md   <- PR summary comment")
    print("  infrastructure-analysis-report.json <- artifact")
    print("  infrastructure-analysis-summary.txt <- notification snippet")
    print("  inline-comments.json                <- Files changed tab comments")


if __name__ == "__main__":
    main()