import json
import requests
import os


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions" 

def load_checkov_report():
    with open("checkov_report.json") as f:
        return json.load(f)

def build_prompt(report):
    failed_checks = report.get("results", {}).get("failed_checks", [])

    if not failed_checks:
        return "No security issues detected in Terraform code."

    summary = ""
    for check in failed_checks:
        summary += f"""
Check ID: {check.get('check_id')}
Resource: {check.get('resource')}
Issue: {check.get('check_name')}
File: {check.get('file_path')}
"""

    prompt = f"""
You are a DevSecOps Terraform Security Reviewer.

Analyze the following Checkov findings and provide:

1. Security Risk
2. Why it is dangerous
3. Recommended Terraform Fix

Findings:
{summary}
"""

    return prompt

def call_llm(prompt):  
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not found in GitHub Secrets")

    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }

  
    models_to_try = [
        "gemini-2.5-flash",             
        "gemini-2.5-flash-lite",        
        "gemini-1.5-flash",             
        "gemini-2.0-flash"              
    ]

    for model in models_to_try:
        print(f"\nTrying model: {model}")

        data = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 1500   
        }

        response = requests.post(
            GEMINI_URL,
            headers=headers,
            json=data
        )

        print("STATUS CODE:", response.status_code)
        print("RAW RESPONSE:", response.text)

        if response.status_code == 200:
            result = response.json()
            if "choices" in result and result["choices"]:
                return result["choices"][0]["message"]["content"]

    raise Exception("All Gemini models failed")

def main():
    print("Loading Checkov report.")
    report = load_checkov_report()

    print("Building prompt.")
    prompt = build_prompt(report)

    print("Calling Gemini AI.")
    analysis = call_llm(prompt)   

    print("Saving AI review.")

    with open("ai_review.txt", "w") as f:
        f.write(analysis)

    print("AI Review Generated Successfully")

if __name__ == "__main__":
    main()