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

# ============================================================================
# FILE LOADING
# ============================================================================

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


# ============================================================================
# DATA EXTRACTION  (Checkov + Infracost -> compact plain-text)
# ============================================================================

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
        code_block = check.get("code_block", [])   # [[line_no, text], ...]

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

    # ── Top-level totals ────────────────────────────────────────────────────
    total_monthly = _safe_float(infracost_data.get("totalMonthlyCost"))
    total_hourly  = _safe_float(infracost_data.get("totalHourlyCost"))
    # If totalMonthlyCost is 0 but hourly exists, derive it
    if total_monthly == 0 and total_hourly > 0:
        total_monthly = total_hourly * 730

    lines = [f"Total monthly cost: ${total_monthly:.2f}  (annual: ${total_monthly*12:.2f})\n"]

    resource_costs = []

    for project in infracost_data.get("projects", []):
        proj_name = project.get("name", "")

        # ── Try both 'breakdown' and 'diff' sections ────────────────────────
        for section_key in ("breakdown", "diff"):
            section = project.get(section_key, {})
            resources = section.get("resources", [])

            # If breakdown/diff is absent, fall back to project-level resources
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

    # De-duplicate: keep the entry with the highest cost per resource name
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
    return tf_sources[:12000]   # cap to avoid token overflow


# ============================================================================
# SINGLE PROMPT
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
# REPORT SAVE
# ============================================================================

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


# ============================================================================
# MAIN
# ============================================================================

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

    print("\nDone.")
    print("  infrastructure-analysis-report.md   <- PR comment")
    print("  infrastructure-analysis-report.json <- artifact")
    print("  infrastructure-analysis-summary.txt <- notification snippet")


if __name__ == "__main__":
    main()