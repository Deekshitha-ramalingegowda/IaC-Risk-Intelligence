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
    print(" google-genai is not installed.")
    print("   Run:  pip install google-genai")
    sys.exit(1)


CHECKOV_JSON = "checkov-local.json"
MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-pro",
]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_json_file(filename):
    """Load and validate JSON file - try multiple encodings"""
    encodings = ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-8', 'latin-1']

    for encoding in encodings:
        try:
            with open(filename, 'r', encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

    print(f"Error: Could not parse {filename} with any encoding")
    return None

def validate_output_files():
    """Ensure both output files exist before analysis"""
    required = ['checkov-output.json', 'infracost-output.json']
    missing = []
    for file in required:
        if not os.path.exists(file):
            missing.append(file)

    if missing:
        return False, f"Missing files: {', '.join(missing)}"
    return True, "All files present"

def get_file_info(filename):
    """Get file size and line count for logging"""
    try:
        size_kb = os.path.getsize(filename) / 1024
        with open(filename, 'r') as f:
            lines = len(f.readlines())
        return size_kb, lines
    except:
        return 0, 0


def load_terraform_sources(terraform_dir="terraform"):
    """
    Load all .tf files from the terraform directory and return them as a
    single annotated string:  «── path/to/file.tf ──»  followed by the
    numbered source lines.  Falls back to the current directory when the
    terraform/ folder is absent (CI runs checkov from repo root).
    """
    search_dirs = [terraform_dir, "."]
    tf_files: dict[str, str] = {}

    for search_dir in search_dirs:
        base = Path(search_dir)
        if base.is_dir():
            for tf_path in sorted(base.rglob("*.tf")):
                rel = str(tf_path)
                if rel not in tf_files:
                    try:
                        text = tf_path.read_text(encoding="utf-8", errors="replace")
                        tf_files[rel] = text
                    except Exception:
                        pass
        if tf_files:
            break          # stop once we found at least one .tf file

    if not tf_files:
        return ""

    parts = []
    for path, content in tf_files.items():
        numbered = "\n".join(
            f"{i+1:4d}  {line}" for i, line in enumerate(content.splitlines())
        )
        parts.append(f"\n\n«── {path} ──»\n{numbered}")

    return "\n".join(parts)



def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print(" GEMINI_API_KEY not set.")
        print("   > Get key: https://aistudio.google.com/app/apikey")
        print("   > Then:    export GEMINI_API_KEY=AIzaSy...")
        sys.exit(1)
    return key

def run_checkov():
    print("\n> Running Checkov (Security Analysis)...\n")

    checkov_path = r"C:\Users\SNAGARAJ\AppData\Local\Programs\Python\Python314\Scripts\checkov.cmd"

    cmd = [
        checkov_path,
        "-d", ".",
        "--framework", "terraform",
        "-o", "json",
        "--soft-fail"
    ]

    print(f"Running command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Save raw output to file for debugging/inspection
    output_file = "checkov-output.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result.stdout if result.stdout else result.stderr)
        print(f"✓ Checkov output saved to: {output_file}\n")
    except Exception as e:
        print(f"⚠ Could not save output file: {e}\n")

    if not result.stdout.strip():
        print("Checkov produced no output:")
        print(result.stderr.strip())
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
        print(f"✓ Successfully parsed Checkov output\n")

        # Debug: Show structure summary
        failed_checks = data.get("results", {}).get("failed_checks", [])
        passed_checks = data.get("results", {}).get("passed_checks", [])
        print(f"  Found {len(failed_checks)} failed checks, {len(passed_checks)} passed checks\n")

        return data
    except json.JSONDecodeError as e:
        print(f"Failed to parse Checkov output: {e}")
        print("Output was:\n", result.stdout[:500])
        sys.exit(1)

def run_infracost():
    print("\n> Running Infracost (Cost Analysis)...\n")

    # Try to find infracost executable
    infracost_paths = [
        "infracost",
        "infracost.exe",
        "infracost.cmd",
        r"C:\Users\SNAGARAJ\AppData\Local\Programs\infracost\infracost.exe",
    ]

    infracost_path = None
    for path in infracost_paths:
        try:
            result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                infracost_path = path
                print(f"Found Infracost: {path}\n")
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if not infracost_path:
        print("⚠ Infracost not found. Skipping cost analysis.")
        print("   To install: choco install infracost (or visit https://www.infracost.io/docs/)")
        return None

    # Check if Infracost API key is set
    if not os.getenv("INFRACOST_API_KEY"):
        print("⚠ Note: INFRACOST_API_KEY environment variable is not set.")
        print("   For full cost analysis, get a free API key from: https://dashboard.infracost.io")
        print("   Then set: export INFRACOST_API_KEY=your-key-here\n")
        return None

    cmd = [
        infracost_path,
        "breakdown",
        "--path", ".",
        "--format", "json"
    ]

    print(f"Running command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Save raw output to file for debugging/inspection
    output_file = "infracost-output.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result.stdout if result.stdout else result.stderr)
        print(f"✓ Infracost output saved to: {output_file}\n")
    except Exception as e:
        print(f"⚠ Could not save output file: {e}\n")

    if result.returncode != 0:
        print(f"⚠ Infracost exited with code {result.returncode}")
        print(f"Error: {result.stderr.strip()[:500]}\n")
        return None

    if not result.stdout.strip():
        print("⚠ Infracost produced no output\n")
        return None

    try:
        data = json.loads(result.stdout)
        print(f"✓ Successfully parsed Infracost output\n")

        # Debug: Show structure summary
        if "results" in data and data["results"]:
            resources_count = 0
            for result_item in data["results"]:
                if "breakdown" in result_item and "resources" in result_item["breakdown"]:
                    resources_count += len(result_item["breakdown"]["resources"])
            print(f"  Found {resources_count} resources with cost data\n")

        return data
    except json.JSONDecodeError as e:
        print(f"⚠ Failed to parse Infracost output: {e}")
        print(f"First 500 chars of output: {result.stdout[:500]}\n")
        return None

def build_security_prompt(checkov_report):
    """Build prompt for security analysis using Checkov data"""
    failed = checkov_report.get("results", {}).get("failed_checks", [])
    if not failed:
        return "No security issues found in Checkov analysis."

    lines = []
    for c in failed:
        check_id   = c.get('check_id',   'UNKNOWN_ID')
        resource   = c.get('resource',   'unknown resource')
        check_name = c.get('check_name', 'No description')

        lines.append(
            f"{check_id} | {resource} | {check_name}"
        )

    findings = "\n".join(lines)

    return f"""You are a security analyst reviewing Terraform infrastructure code using Checkov.

Analyze these security issues and provide concise recommendations:

SECURITY FINDINGS:
{findings}

For each finding above, provide:
1. Risk severity (CRITICAL/HIGH/MEDIUM/LOW)
2. Why it's a security issue
3. Quick remediation steps (1-2 lines max per step)

Format your response as:
CHECK_ID | SEVERITY | ISSUE | REMEDIATION

Keep it brief and actionable. No explanations or preambles."""


def build_cost_prompt(infracost_data):
    """Build prompt for cost analysis using Infracost data"""
    if not infracost_data:
        return "No cost data available."

    # Infracost JSON structure: projects[0].breakdown.resources[]
    # Extract the total monthly cost from top level or from projects
    total_cost = infracost_data.get("totalMonthlyCost", 0)
    if isinstance(total_cost, str):
        total_cost = float(total_cost)

    resource_data = []

    # Get resources from projects
    projects = infracost_data.get("projects", [])
    if not projects:
        return "No projects found in cost analysis."

    for project in projects:
        breakdown = project.get("breakdown", {})
        resources = breakdown.get("resources", [])

        for resource in resources:
            name = resource.get("name", "unknown")
            resource_type = resource.get("resourceType", "unknown")
            costs = resource.get("costComponents", [])

            monthly_cost = 0
            for cost in costs:
                if "monthlyCost" in cost and cost["monthlyCost"]:
                    try:
                        monthly_cost += float(cost["monthlyCost"])
                    except (ValueError, TypeError):
                        pass

            # Also check subresources
            subresources = resource.get("subresources", [])
            for subresouce in subresources:
                subcosts = subresouce.get("costComponents", [])
                for cost in subcosts:
                    if "monthlyCost" in cost and cost["monthlyCost"]:
                        try:
                            monthly_cost += float(cost["monthlyCost"])
                        except (ValueError, TypeError):
                            pass

            if monthly_cost > 0:
                resource_data.append({
                    "name": name,
                    "type": resource_type,
                    "cost": monthly_cost
                })

    if not resource_data:
        return "No billable resources found."

    # Sort by cost (highest first)
    resource_data.sort(key=lambda x: x["cost"], reverse=True)

    # Build findings string
    findings = []
    findings.append(f"TOTAL MONTHLY COST: ${total_cost:.2f}\n")
    findings.append("TOP RESOURCE COSTS:")

    for i, res in enumerate(resource_data[:15], 1):  # Top 15
        findings.append(f"{i}. {res['name']} ({res['type']}): ${res['cost']:.2f}/month")

    findings_text = "\n".join(findings)

    return f"""You are a cloud cost optimization expert reviewing AWS Terraform infrastructure.

Analyze these resources and their monthly costs:

{findings_text}

Provide cost optimization recommendations:
1. Identify oversized resources that could be downsized
2. Highlight unused resources that should be removed
3. Suggest better instance types or configurations
4. Estimate potential monthly savings

Format your response concisely with:
- Resource name that needs optimization
- Current cost and suggested change
- Estimated savings per month

Be specific with amounts and actionable recommendations."""


# ============================================================================
# DEEP ANALYSIS PROMPT BUILDERS
# ============================================================================

def build_security_deep_prompt(checkov_data):
    """Build a compact, PR-comment-ready security prompt from Checkov findings + TF source."""

    failed_checks = checkov_data.get("results", {}).get("failed_checks", [])

    # ── Collect per-check detail: id, name, resource, file, lines, code snippet ──
    findings = []
    for check in failed_checks:
        line_range  = check.get("file_line_range", [])
        code_block  = check.get("code_block", [])   # [[line_no, text], ...]
        snippet     = "\n".join(
            f"{ln}: {code.rstrip()}" for ln, code in (code_block or [])[:8]
        )
        findings.append({
            "id":       check.get("check_id", ""),
            "name":     check.get("check_name", ""),
            "resource": check.get("resource", "unknown"),
            "file":     check.get("file_path", ""),
            "lines":    f"{line_range[0]}-{line_range[1]}" if len(line_range) == 2 else "",
            "snippet":  snippet,
        })

    # ── Serialise findings for the prompt ────────────────────────────────────
    findings_text = ""
    for f in findings[:30]:
        loc = f"{f['file']}:{f['lines']}" if f["lines"] else f["file"]
        findings_text += (
            f"\n[{f['id']}] {f['resource']}  ({loc})\n"
            f"  Rule: {f['name']}\n"
        )
        if f["snippet"]:
            findings_text += f"  Code:\n    {f['snippet'].replace(chr(10), chr(10)+'    ')}\n"

    tf_sources = load_terraform_sources()
    tf_section = f"\nTERRAFORM SOURCE:\n{tf_sources[:10000]}\n" if tf_sources else ""

    return f"""You are a Terraform security reviewer writing a GitHub PR comment.

CHECKOV FINDINGS  ({len(failed_checks)} failed checks):
{findings_text}
{tf_section}

OUTPUT RULES — follow exactly, no exceptions:
- Write ONLY the findings table and per-finding fix blocks below.
- No introductions, no summaries, no explanations outside the blocks.
- Every finding must reference the EXACT offending line(s) from the source above.
- Keep "Why risky" to one sentence. Keep "Fix" to the minimum changed lines only.

══════════════════════════════
OUTPUT FORMAT
══════════════════════════════

## 🔒 Security Findings

| # | Severity | Check | Resource | File:Line |
|---|----------|-------|----------|-----------|
(one row per finding, severity = CRITICAL/HIGH/MEDIUM/LOW)

---

Then for each CRITICAL and HIGH finding only, one block:

**[CHECK_ID] `resource_type.resource_name`** · `file:line`

> ⚠️ Why risky: _one sentence — name the exact attack or exposure_

```diff
- <the exact bad line(s) from source>
+ <the corrected line(s) — minimum change only>
```

> ✅ Fix: _one sentence on what this change does_

---

After all blocks:

**Security verdict:** `BLOCK` / `REQUEST CHANGES` / `APPROVE`
Blockers before merge: list check IDs only, one line each."""


def build_cost_deep_prompt(infracost_data):
    """Build a compact, PR-comment-ready cost prompt from Infracost data + TF source."""

    total_cost = float(infracost_data.get('totalMonthlyCost', 0) or 0)

    # ── Extract per-resource costs with components ────────────────────────────
    resource_costs = []
    for project in infracost_data.get("projects", []):
        for resource in project.get("breakdown", {}).get("resources", []):
            name          = resource.get("name", "unknown")
            resource_type = resource.get("resourceType", "unknown")
            monthly_cost  = 0.0
            components    = []

            for cost in resource.get("costComponents", []):
                try:
                    c = float(cost.get("monthlyCost") or 0)
                    monthly_cost += c
                    if c > 0:
                        components.append(
                            f"{cost.get('description','')}: "
                            f"{cost.get('monthlyQuantity','')} {cost.get('unit','')} = ${c:.2f}"
                        )
                except (ValueError, TypeError):
                    pass
            for sub in resource.get("subresources", []):
                for cost in sub.get("costComponents", []):
                    try:
                        monthly_cost += float(cost.get("monthlyCost") or 0)
                    except (ValueError, TypeError):
                        pass

            if monthly_cost > 0:
                resource_costs.append({
                    "name":       name,
                    "type":       resource_type,
                    "cost":       monthly_cost,
                    "components": components[:3],
                })

    resource_costs.sort(key=lambda x: x["cost"], reverse=True)

    cost_lines = [f"Total monthly cost: ${total_cost:.2f}  (annual: ${total_cost*12:.2f})\n"]
    for i, r in enumerate(resource_costs[:12], 1):
        cost_lines.append(f"{i}. {r['name']} ({r['type']}): ${r['cost']:.2f}/mo")
        for c in r["components"]:
            cost_lines.append(f"   • {c}")
    cost_summary = "\n".join(cost_lines)

    tf_sources = load_terraform_sources()
    tf_section = f"\nTERRAFORM SOURCE:\n{tf_sources[:10000]}\n" if tf_sources else ""

    return f"""You are a Terraform cost reviewer writing a GitHub PR comment.

INFRACOST BREAKDOWN:
{cost_summary}
{tf_section}

OUTPUT RULES — follow exactly, no exceptions:
- Write ONLY the table and per-resource fix blocks below.
- No introductions, no general advice paragraphs.
- For each resource: quote the EXACT current attribute(s) from source, show ONLY the changed lines in diff format.
- Keep "Why expensive" to one sentence. Sizing rationale to one sentence.

══════════════════════════════
OUTPUT FORMAT
══════════════════════════════

## 💰 Cost Findings

| Resource | Current Config | $/mo | Recommended Config | New $/mo | Monthly Saving |
|----------|---------------|------|--------------------|----------|----------------|
(one row per resource costing > $20/mo — use actual resource names from Infracost)

**Total potential saving: $XX/mo ($XX/yr)**

---

Then for each resource costing > $50/month, one block:

**`resource_type.resource_name`** · `$XX/mo`

> 💸 Why expensive: _one sentence_

```diff
- <exact current attribute(s) from source — e.g. instance_type = "m5.2xlarge">
+ <replacement — e.g. instance_type = "t3.large">
```

> 💡 Why sufficient: _one sentence on why the smaller size works_
> ⏱ Effort: X min · Downtime: None / X-min window · Risk: Low/Medium

---

After all blocks:

**Cost verdict:** `BLOCK — EXCESSIVE COSTS` / `NEEDS OPTIMISATION` / `ACCEPTABLE`
Quick wins (zero downtime): list resource names + saving, one line each."""


def build_executive_summary_prompt(security_analysis, cost_analysis):
    """Build a compact merge-decision header that stitches security + cost verdicts."""

    return f"""You are a lead engineer writing the opening block of a GitHub PR comment.

You have a security review and a cost review (both already written below).
Write ONLY the header summary block — the detailed sections already exist.

SECURITY REVIEW:
{security_analysis[:3000]}

COST REVIEW:
{cost_analysis[:3000]}

OUTPUT RULES:
- Maximum 30 lines total.
- No bullet-point essays. No roadmaps. No 30-day plans.
- Tables only where specified below.
- Extract the verdicts and numbers already present in the reviews above — do not invent new ones.

══════════════════════════════
OUTPUT FORMAT (produce exactly this, filled in)
══════════════════════════════

## 🏗️ Infrastructure PR Analysis

| | Security | Cost |
|-|----------|------|
| **Status** | 🔴 BLOCK / 🟡 CHANGES / 🟢 OK | 🔴 BLOCK / 🟡 OPTIMISE / 🟢 OK |
| **Top issue** | _one phrase_ | _one phrase_ |
| **Findings** | X critical, Y high | $XX/mo · $XX/yr saving possible |

**Merge decision: ❌ REQUEST CHANGES** _(or ✅ APPROVE / ⚠️ APPROVE WITH CONDITIONS)_

**Must fix before merge:**
- `resource.name` — one-line reason (from security review)
- `resource.name` — one-line reason (if any)

**Can fix after merge:**
- `resource.name` — saving $XX/mo or security note — effort X min

---
_(Security details · Cost details below)_"""


def ask_gemini(prompt, api_key, analysis_type="security"):
    print(f"\n> Querying Gemini for {analysis_type} analysis...\n")

    client = genai.Client(api_key=api_key)

    for model_name in MODELS:
        print(f"  Trying {model_name} ... ", end="")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"temperature": 0.2, "max_output_tokens": 16000}
            )
            text = response.text.strip()
            if text:
                print("OK")
                return text
            else:
                print("empty response")
        except Exception as e:
            print(f"failed > {str(e)[:80]}...")

    print(f"\n All models failed for {analysis_type} analysis.")
    return f"Failed to get {analysis_type} analysis from Gemini."


# ============================================================================
# DEEP ANALYSIS FUNCTIONS
# ============================================================================

def analyze_security_deep(checkov_data, api_key):
    """Deep security analysis using full Checkov JSON"""
    if not checkov_data:
        return "Unable to perform deep security analysis - no Checkov data available."

    size_kb, lines = get_file_info("checkov-output.json")
    print(f"Processing Checkov report: {size_kb:.1f} KB ({lines:,} lines)")

    prompt = build_security_deep_prompt(checkov_data)
    return ask_gemini(prompt, api_key, "deep security analysis")

def analyze_cost_deep(infracost_data, api_key):
    """Deep cost analysis using full Infracost JSON"""
    if not infracost_data:
        return "Unable to perform deep cost analysis - no Infracost data available."

    size_kb, lines = get_file_info("infracost-output.json")
    print(f"Processing Infracost report: {size_kb:.1f} KB ({lines:,} lines)")

    prompt = build_cost_deep_prompt(infracost_data)
    return ask_gemini(prompt, api_key, "deep cost analysis")

def create_executive_summary(security_analysis, cost_analysis, api_key):
    """Create executive summary combining both analyses"""
    if not security_analysis or not cost_analysis:
        return "Unable to create executive summary - missing analysis data."

    prompt = build_executive_summary_prompt(security_analysis, cost_analysis)
    return ask_gemini(prompt, api_key, "executive summary")


# ============================================================================
# REPORT GENERATION FUNCTIONS
# ============================================================================

def display_comprehensive_report(security_analysis, cost_analysis, executive_summary):
    """Display comprehensive report with all three analyses"""

    report = []
    report.append("\n" + "="*100)
    report.append("  INFRASTRUCTURE ANALYSIS REPORT (Checkov + Infracost + Gemini Deep Analysis)")
    report.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("="*100)

    # Executive Summary
    report.append("\n" + "-"*100)
    report.append("EXECUTIVE SUMMARY")
    report.append("-"*100 + "\n")
    report.append(executive_summary)

    # Security Analysis
    report.append("\n" + "-"*100)
    report.append("DEEP SECURITY ANALYSIS")
    report.append("-"*100 + "\n")
    report.append(security_analysis)

    # Cost Analysis
    report.append("\n" + "-"*100)
    report.append("DEEP COST ANALYSIS & OPTIMIZATION")
    report.append("-"*100 + "\n")
    report.append(cost_analysis)

    report.append("\n" + "="*100)

    output = "\n".join(report)
    print(output)
    return output

def save_report_to_file(security_analysis, cost_analysis, executive_summary, output_dir="."):
    """Save report to multiple formats for GitHub Actions"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Markdown (PR comment) ──────────────────────────────────────────────
    # Structure: header summary → security findings → cost findings
    md_filename = f"{output_dir}/infrastructure-analysis-report.md"
    md_content = f"""{executive_summary}

---

## 🔒 Security Analysis

{security_analysis}

---

## 💰 Cost Analysis

{cost_analysis}

---
*Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · Checkov + Infracost + Gemini*
"""

    try:
        with open(md_filename, 'w', encoding='utf-8') as f:
            f.write(md_content)
        print(f"\n✓ Markdown report saved: {md_filename}")
    except Exception as e:
        print(f"\n⚠ Failed to save markdown report: {e}")

    # ── JSON (artifacts) ──────────────────────────────────────────────────
    json_filename = f"{output_dir}/infrastructure-analysis-report.json"
    try:
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "analyses": {
                    "executive_summary": executive_summary,
                    "security_analysis": security_analysis,
                    "cost_analysis":     cost_analysis,
                }
            }, f, indent=2)
        print(f"✓ JSON report saved: {json_filename}")
    except Exception as e:
        print(f"⚠ Failed to save JSON report: {e}")

    # ── Plain-text summary ────────────────────────────────────────────────
    txt_filename = f"{output_dir}/infrastructure-analysis-summary.txt"
    try:
        with open(txt_filename, 'w', encoding='utf-8') as f:
            f.write(
                f"INFRASTRUCTURE ANALYSIS SUMMARY\n"
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{executive_summary[:800]}\n\n"
                f"Full report: infrastructure-analysis-report.md\n"
            )
        print(f"✓ Text summary saved: {txt_filename}")
    except Exception as e:
        print(f"⚠ Failed to save text summary: {e}")


def main():
    key = get_gemini_key()

    # Validate and load output files
    print("\n> Validating analysis output files...\n")
    valid, msg = validate_output_files()

    if not valid:
        print(f"Error: {msg}")
        print("\nFirst, run the security and cost analysis:")
        print("  1. Run Checkov: checkov -d . --framework terraform -o json")
        print("  2. Run Infracost: infracost breakdown -p . --format json")
        sys.exit(1)

    print(f"✓ {msg}\n")

    # Load the JSON data files
    print("> Loading analysis data files...")
    checkov_data = load_json_file("checkov-output.json")
    infracost_data = load_json_file("infracost-output.json")

    if not checkov_data or not infracost_data:
        print("Error: Failed to load analysis data files")
        sys.exit(1)

    # Run deep analyses in sequence (can be parallelized with threading if needed)
    print("\n" + "="*100)
    print("INITIATING DEEP INFRASTRUCTURE ANALYSIS")
    print("="*100)

    # Deep Security Analysis
    print("\nStep 1/3: Deep Security Analysis")
    print("-" * 100)
    security_analysis = analyze_security_deep(checkov_data, key)

    # Deep Cost Analysis
    print("\nStep 2/3: Deep Cost Analysis")
    print("-" * 100)
    cost_analysis = analyze_cost_deep(infracost_data, key)

    # Executive Summary
    print("\nStep 3/3: Creating Executive Summary")
    print("-" * 100)
    executive_summary = create_executive_summary(security_analysis, cost_analysis, key)

    # Display comprehensive report
    print("\n")
    display_comprehensive_report(security_analysis, cost_analysis, executive_summary)

    # Save reports to files (for GitHub Actions integration)
    print("\nSaving analysis reports...")
    save_report_to_file(security_analysis, cost_analysis, executive_summary)

    print("\n✓ Analysis complete!")
    print("\nOutput files generated:")
    print("  - infrastructure-analysis-report.md (Markdown format for PR comments)")
    print("  - infrastructure-analysis-report.json (Full data for artifacts)")
    print("  - infrastructure-analysis-summary.txt (Brief summary for notifications)")


if __name__ == "__main__":
    main()