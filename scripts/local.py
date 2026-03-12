#!/usr/bin/env python3

import os
import sys
import json
import subprocess
import shutil
from google import genai


MODEL = "models/gemini-2.5-flash"


# ==========================================================
# UTIL
# ==========================================================

def tool_exists(name):
    return shutil.which(name) is not None


def run_cmd(cmd):

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("Command failed:", " ".join(cmd))
        print(result.stderr)

    return result.stdout


def get_gemini_key():

    key = os.getenv("GEMINI_API_KEY")

    if not key:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)

    return key


# ==========================================================
# TERRAFORM PLAN
# ==========================================================

def generate_plan():

    if not tool_exists("terraform"):
        print("⚠ Terraform not found. Skipping Terraform plan.")
        return "Terraform plan unavailable."

    print("Running Terraform init...")

    run_cmd([
        "terraform",
        "init",
        "-input=false",
        "-backend=false"
    ])

    print("Running Terraform plan...")

    run_cmd([
        "terraform",
        "plan",
        "-no-color",
        "-out=tfplan"
    ])

    print("Generating plan text...")

    plan_text = run_cmd([
        "terraform",
        "show",
        "-no-color",
        "tfplan"
    ])

    with open("terraform-plan.txt", "w") as f:
        f.write(plan_text)

    try:

        json_plan = run_cmd([
            "terraform",
            "show",
            "-json",
            "tfplan"
        ])

        with open("plan.json", "w") as f:
            f.write(json_plan)

    except:
        pass

    return plan_text[:8000]


# ==========================================================
# CHECKOV
# ==========================================================

def run_checkov():

    if not tool_exists("checkov"):
        print("⚠ Checkov not installed. Skipping security scan.")
        return {}

    print("Running Checkov security scan...")

    cmd = [
        "checkov",
        "-d", ".",
        "--framework", "terraform",
        "-o", "json"
    ]

    output = run_cmd(cmd)

    with open("checkov-output.json", "w") as f:
        f.write(output)

    try:
        return json.loads(output)
    except:
        return {}


def parse_checkov(data):

    failed = []

    if isinstance(data, list):
        for entry in data:
            failed.extend(entry.get("results", {}).get("failed_checks", []))
    else:
        failed = data.get("results", {}).get("failed_checks", [])

    if not failed:
        return "No security issues detected."

    findings = []

    for c in failed[:100]:

        cid = c.get("check_id")
        resource = c.get("resource")
        name = c.get("check_name")

        findings.append(
            f"{cid} | {resource} | {name}"
        )

    return "\n".join(findings)


# ==========================================================
# INFRACOST
# ==========================================================

def run_infracost():

    if not tool_exists("infracost"):
        print("⚠ Infracost not installed. Skipping cost analysis.")
        return {}

    if not os.path.exists("plan.json"):
        print("⚠ Terraform plan.json not found. Skipping cost analysis.")
        return {}

    print("Running Infracost cost analysis...")

    cmd = [
        "infracost",
        "breakdown",
        "--path",
        "plan.json",
        "--format",
        "json"
    ]

    output = run_cmd(cmd)

    with open("infracost-output.json", "w") as f:
        f.write(output)

    try:
        return json.loads(output)
    except:
        return {}


def parse_cost(data):

    if not data:
        return "No cost data available."

    resources = []

    for project in data.get("projects", []):

        for r in project.get("breakdown", {}).get("resources", []):

            name = r.get("name")
            rtype = r.get("resourceType")

            monthly = 0

            for comp in r.get("costComponents", []):

                value = comp.get("monthlyCost")

                try:
                    if value:
                        monthly += float(value)
                except:
                    pass

            if monthly > 0:

                resources.append(
                    f"{name} ({rtype}) : ${monthly:.2f}/month"
                )

    if not resources:
        return "No billable resources detected."

    return "\n".join(resources[:50])


# ==========================================================
# PROMPT
# ==========================================================

def build_prompt(plan, security, cost):

    return f"""
You are a Principal Cloud Architect reviewing a Terraform infrastructure change.

Inputs provided:
1. Terraform plan
2. Checkov security scan
3. Infracost cost analysis

Your task:

Identify issues and provide actionable recommendations.

For each issue include:

Finding
Risk
Cost Impact
Root Cause
Recommendation
Steps to Fix
Terraform Fix Example

Organize the output under these sections:

Infrastructure Changes
Security Issues
Cost Impact
Reliability Concerns
Architecture Anti-Patterns

Rules:
- Only analyze the provided inputs
- Do not invent resources
- Be concise and actionable
- If cost increase is detected explain the reason

Terraform Plan:
{plan}

Checkov Findings:
{security}

Cost Breakdown:
{cost}
"""


# ==========================================================
# GEMINI
# ==========================================================

def ask_gemini(prompt, api_key):

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 4000
        }
    )

    if response and response.text:
        return response.text

    return "AI returned empty response."


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("\nStarting AI Infrastructure Analysis\n")

    key = get_gemini_key()

    plan = generate_plan()

    checkov_data = run_checkov()
    infracost_data = run_infracost()

    security = parse_checkov(checkov_data)
    cost = parse_cost(infracost_data)

    prompt = build_prompt(plan, security, cost)

    print("\nRunning AI infrastructure analysis...\n")

    result = ask_gemini(prompt, key)

    print("\n" + "=" * 80)
    print("AI INFRASTRUCTURE REVIEW")
    print("=" * 80)

    print(result)

    print("=" * 80)

    with open("ai-infra-review.txt", "w") as f:
        f.write(result)

    print("\nReport saved to ai-infra-review.txt\n")


if __name__ == "__main__":
    main()