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
    """Create deep security analysis prompt with OPTIMIZED Checkov data (token-efficient)"""

    # Extract only FAILED checks - ignore passed checks to save tokens
    failed_checks = checkov_data.get("results", {}).get("failed_checks", [])

    # Group by resource for easier analysis
    checks_by_resource = {}
    for check in failed_checks:
        resource = check.get("resource", "unknown")
        check_id = check.get("check_id", "unknown")
        check_name = check.get("check_name", "")

        if resource not in checks_by_resource:
            checks_by_resource[resource] = []
        checks_by_resource[resource].append({
            "id": check_id,
            "name": check_name,
            "file": check.get("file_path", ""),
            "file_abs_path": check.get("file_abs_path", "")
        })

    # Build concise summary (NOT full JSON - saves 80% tokens!)
    summary = f"""CHECKOV SECURITY ANALYSIS SUMMARY
Total failed checks: {len(failed_checks)}

FAILED CHECKS BY RESOURCE:
"""

    for resource, checks in sorted(checks_by_resource.items())[:20]:  # Top 20 resources
        summary += f"\n{resource}:\n"
        for check in checks[:5]:  # Top 5 checks per resource
            summary += f"  - {check['id']}: {check['name']}\n"

    return f"""You are a security architect analyzing Terraform infrastructure security posture.

ANALYZE THIS SECURITY SUMMARY - PROVIDE DETAILED, ACTIONABLE ANALYSIS:

{summary}

Your analysis MUST include specific details for each CRITICAL finding:

1. CRITICAL SECURITY THREATS (detailed):
   For each CRITICAL finding, provide:
   - Resource affected: [specific resource name]
   - Security threat: [specific attack vector and vulnerability]
   - Data/Access at risk: [what data or services are exposed]
   - Likelihood of exploitation: HIGH/MEDIUM/LOW
   - Potential impact: [data breach, unauthorized access, etc.]
   - Compliance violations: [HIPAA, PCI-DSS, SOC2, CIS Benchmarks if applicable]

   MITIGATION STEPS (be specific):
   1. Exact Terraform code change needed
   2. Effort estimate: X hours
   3. Downtime/Performance impact
   4. Testing/Validation method
   5. Rollback plan

2. RISK SCORECARD (per resource):
   Format: [resource_name]: [score]/100 ([SEVERITY])
   - Include top 10 highest-risk resources

3. ATTACK SCENARIO ANALYSIS:
   - Most likely attack path
   - Step-by-step exploitation
   - Timeline to exploitation if not fixed

4. REMEDIATION ROADMAP:
   IMMEDIATE (within 24 hours):
   - [Critical fix with 1-sentence impact]

   SHORT-TERM (1 week):
   - [High-priority fix]

5. INFRASTRUCTURE SECURITY GRADE:
   Current Grade: [A-F]
   Target Grade: A+
   Recommendation: [APPROVE/NEEDS FIXES/BLOCK]

Reference all Checkov check IDs. Be VERY SPECIFIC with actual fixes needed."""


def build_cost_deep_prompt(infracost_data):
    """Create deep cost analysis prompt with OPTIMIZED Infracost data (token-efficient)"""

    # Extract key cost data without full JSON dump
    total_cost = float(infracost_data.get('totalMonthlyCost', 0))

    # Extract resources with their costs
    resource_costs = []
    projects = infracost_data.get("projects", [])

    for project in projects:
        breakdown = project.get("breakdown", {})
        resources = breakdown.get("resources", [])

        for resource in resources:
            name = resource.get("name", "unknown")
            resource_type = resource.get("resourceType", "unknown")

            monthly_cost = 0
            cost_components = []

            # Sum all cost components for this resource
            costs = resource.get("costComponents", [])
            for cost in costs:
                if "monthlyCost" in cost and cost["monthlyCost"]:
                    try:
                        monthly_cost += float(cost["monthlyCost"])
                        cost_components.append({
                            "description": cost.get("description", ""),
                            "price": float(cost.get("monthlyCost", 0))
                        })
                    except (ValueError, TypeError):
                        pass

            # Include subresources
            subresources = resource.get("subresources", [])
            for subresouce in subresources:
                subcosts = subresouce.get("costComponents", [])
                for cost in subcosts:
                    if "monthlyCost" in cost and cost["monthlyCost"]:
                        try:
                            monthly_cost += float(cost.get("monthlyCost", 0))
                        except (ValueError, TypeError):
                            pass

            if monthly_cost > 0:
                resource_costs.append({
                    "name": name,
                    "type": resource_type,
                    "cost": monthly_cost,
                    "components": cost_components[:3]  # Top 3 cost components per resource
                })

    # Sort by cost descending
    resource_costs.sort(key=lambda x: x["cost"], reverse=True)

    # Build summary with only TOP resources
    summary = f"""INFRACOST COST ANALYSIS SUMMARY
Total Monthly Cost: ${total_cost:.2f}
Total Annual Cost: ${total_cost*12:.2f}

TOP 10 RESOURCES BY COST:
"""

    for i, res in enumerate(resource_costs[:10], 1):
        summary += f"\n{i}. {res['name']} ({res['type']}): ${res['cost']:.2f}/month\n"
        if res['components']:
            for comp in res['components']:
                if comp['description'] and comp['price'] > 0:
                    summary += f"   - {comp['description']}: ${comp['price']:.2f}\n"

    # Add cost breakdown by category
    summary += f"\n\nCOST SUMMARY BY CATEGORY:"
    cost_by_type = {}
    for res in resource_costs:
        res_type = res['type'].split('.')[-1] if '.' in res['type'] else res['type']
        if res_type not in cost_by_type:
            cost_by_type[res_type] = 0
        cost_by_type[res_type] += res['cost']

    for res_type in sorted(cost_by_type.keys(), key=lambda x: cost_by_type[x], reverse=True)[:10]:
        summary += f"\n{res_type}: ${cost_by_type[res_type]:.2f}/month"

    return f"""You are a cloud cost optimization expert analyzing AWS infrastructure costs.

ANALYZE THIS COST SUMMARY - PROVIDE DETAILED COST OPTIMIZATION STRATEGY:

{summary}

Your analysis MUST include specific technical and financial details:

1. RESOURCE-BY-RESOURCE OPTIMIZATION (focus on top 5 most expensive resources):

   For each expensive resource (>$100/month):

   Current Configuration:
   - Resource name: [actual resource name]
   - Type: [instance/volume type]
   - Current monthly cost: $XXX
   - Annual cost: $XXX

   ALTERNATIVE OPTIONS (evaluate 2-3 similar types):
   Option 1: [Downsized alternative type]
   - Monthly cost: $XXX (savings: $XXX, or X% reduction)
   - Feasibility: [LOW/MEDIUM/HIGH]
   - Implementation effort: X hours
   - Downtime risk: [None/Minimal/Significant]
   - Performance impact: [None/Minimal/Significant]
   - Testing needed: [what to validate]
   - Recommendation: [RECOMMENDED/CONSIDER/NOT RECOMMENDED]

   BEST CHOICE: [Which option with justification]

2. COST BREAKDOWN & COMPARISON TABLE:
   Resource | Current Type | Monthly Cost | Recommended | Monthly Savings | Effort
   ---------|--------------|-------------|-------------|-----------------|-------
   [List top 5 most expensive resources with recommendations]

   TOTAL MONTHLY SAVINGS POTENTIAL: $XXX
   TOTAL ANNUAL SAVINGS: $XXX

3. SAVINGS OPPORTUNITIES BY PRIORITY:

   Compute Optimization:
   - [Specific instance downsizing suggestions] = $XXX/month
   - [Unused or oversized resources] = $XXX/month

   Storage Optimization:
   - [EBS volume adjustments] = $XXX/month
   - [Unused volumes to delete] = $XXX/month

   Network Optimization:
   - [NAT Gateway or data transfer reduction] = $XXX/month

4. IMPLEMENTATION ROADMAP:

   IMMEDIATE (within days - quick wins):
   - [Delete unused resources]
   - Savings: $XX/month
   - Downtime: None
   - Effort: 1-2 hours

   SHORT-TERM (1-2 weeks - requires testing):
   - [Instance downsizing or type changes]
   - Savings: $XXX/month
   - Downtime: [Specify if any]
   - Effort: X hours (including testing)

5. COST EFFICIENCY METRICS:

   Current state: ${total_cost:.2f}/month (${total_cost*12:.2f}/year)
   With optimizations: $XXX/month ($XXX/year)

   Total savings potential: X% reduction
   Cost Efficiency Grade: [A-F]

   Break-even timeline: X weeks for any migration efforts

PROVIDE SPECIFIC INSTANCE TYPES, EXACT NUMBERS, and feasibility analysis.
Recommendation: [MERGE - COST ACCEPTABLE / MERGE - NEEDS COST OPTIMIZATION / BLOCK - EXCESSIVE COSTS]"""


def build_executive_summary_prompt(security_analysis, cost_analysis):
    """Create comprehensive executive summary combining both analyses"""

    return f"""You are a CTO/Cloud Architect reviewing infrastructure audit findings for a PR merge decision.

SYNTHESIZE THESE TWO ANALYSES INTO A STRATEGIC EXECUTIVE SUMMARY:

SECURITY ANALYSIS FINDINGS:
{security_analysis}

---

COST ANALYSIS FINDINGS:
{cost_analysis}

---

CREATE AN EXECUTIVE REPORT FOR PR MERGE DECISION with:

1. INFRASTRUCTURE HEALTH SCORECARD:
   Overall Grade: [A-F with clear reasoning]
   - What's the most critical issue preventing an A grade?

   Security Grade: [A-F]
   - List top 3 security issues preventing higher grade

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

    # Save as Markdown (for PR comments)
    md_filename = f"{output_dir}/infrastructure-analysis-report.md"
    md_content = f"""# Infrastructure Analysis Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Executive Summary

{executive_summary}

---

## Security Analysis (Deep)

{security_analysis}

---

## Cost Analysis & Optimization (Deep)

{cost_analysis}

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

    try:
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(json_content, f, indent=2)
        print(f"✓ JSON report saved: {json_filename}")
    except Exception as e:
        print(f"⚠ Failed to save JSON report: {e}")

    # Save summary as text (for email/notifications)
    txt_filename = f"{output_dir}/infrastructure-analysis-summary.txt"
    txt_content = f"""INFRASTRUCTURE ANALYSIS SUMMARY
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

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
