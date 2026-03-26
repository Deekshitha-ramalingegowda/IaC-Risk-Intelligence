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


# ============================================================
# CHECKOV
# ============================================================

def run_checkov():
    print("\nRunning Checkov...\n")

    cmd = [
        "checkov",
        "-d", ".",
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
        print(f"Checkov complete: {len(failed)} failed checks")
        return data
    except Exception:
        print("Checkov JSON parse failed")
        return None


# ============================================================
# INFRACOST
# ============================================================

def run_infracost():
    print("\nRunning Infracost...\n")

    if not os.getenv("INFRACOST_API_KEY"):
        print("INFRACOST_API_KEY missing — skipping cost analysis")
        return None

    cmd = [
        "infracost",
        "breakdown",
        "--path", ".",
        "--format", "json",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("Infracost failed")
        return None

    with open(INFRACOST_JSON, "w", encoding="utf-8") as f:
        f.write(result.stdout)

    try:
        return json.loads(result.stdout)
    except:
        return None


# ============================================================
# PROMPTS
# ============================================================

def build_security_deep_prompt(checkov_data):

    failed = checkov_data.get("results", {}).get("failed_checks", [])

    summary = f"Total failed checks: {len(failed)}\n"

    for check in failed[:30]:
        summary += f"{check.get('check_id')} | {check.get('resource')} | {check.get('check_name')}\n"

    return f"""
You are a Cloud Security Architect.

Analyze Terraform security findings.

{summary}

Provide:
1. Critical risks
2. Attack scenarios
3. Exact Terraform fixes
4. Risk grading (A-F)
5. Remediation roadmap
"""


def build_cost_deep_prompt(infracost_data):

    if not infracost_data:
        return "No cost data available."

    total_cost = float(infracost_data.get("totalMonthlyCost", 0))

    return f"""
You are a FinOps Architect.

Monthly Cost: ${total_cost}

Provide:
- Oversized resources
- Cost savings opportunities
- Downsizing suggestions
- Estimated savings
- Cost efficiency grade
"""


def build_executive_summary_prompt(sec, cost):

    return f"""
You are a CTO reviewing infrastructure PR.

SECURITY ANALYSIS:
{sec}

COST ANALYSIS:
{cost}

Provide EXECUTIVE MERGE DECISION:
- Overall Grade
- Security Grade
- Cost Grade
- Merge Recommendation
- 30 Day Roadmap
"""


# ============================================================
# GEMINI CALL
# ============================================================

def ask_gemini(prompt, api_key, name):

    print(f"\nGemini Analysis → {name}")

    client = genai.Client(api_key=api_key)

    for model in MODELS:
        try:
            print(f"Trying {model}")
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.2,
                    "max_output_tokens": 8192,
                },
            )

            if response.text:
                return response.text.strip()

        except Exception as e:
            print(f"Failed: {e}")

    return "Gemini analysis failed."


# ============================================================
# DEEP ANALYSIS
# ============================================================

def analyze_security_deep(checkov_data, api_key):

    if not checkov_data:
        return "No security data."

    size_kb, lines = get_file_info(CHECKOV_JSON)
    print(f"Security file size: {size_kb} KB | {lines} lines")

    prompt = build_security_deep_prompt(checkov_data)
    return ask_gemini(prompt, api_key, "Security")


def analyze_cost_deep(infracost_data, api_key):

    if not infracost_data:
        return "No cost data."

    size_kb, lines = get_file_info(INFRACOST_JSON)
    print(f"Cost file size: {size_kb} KB | {lines} lines")

    prompt = build_cost_deep_prompt(infracost_data)
    return ask_gemini(prompt, api_key, "Cost")


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

    report_file = "infrastructure-analysis-report.md"

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# IaC Risk Intelligence Report\n\n")
        f.write("## Security Analysis\n")
        f.write(security_analysis)
        f.write("\n\n## Cost Analysis\n")
        f.write(cost_analysis)
        f.write("\n\n## Executive Summary\n")
        f.write(executive_summary)

    print(f"\nReport generated: {report_file}")
    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()