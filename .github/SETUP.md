# Infrastructure Analysis GitHub Actions Workflow

## 📋 Overview

This GitHub Actions workflow automatically analyzes your Terraform infrastructure for security risks and costs using a three-stage pipeline:

1. **Checkov** - Security vulnerability scanning
2. **Infracost** - Cost estimation & optimization
3. **Gemini AI** - Deep intelligence analysis with actionable recommendations

## 🚀 Setup Instructions

### 1. Add GitHub Secrets

The workflow requires two API keys. Add them to your GitHub repository:

**Settings → Secrets and variables → Actions → New repository secret**

#### Required Secrets:

| Secret Name | Value | Where to Get |
|------------|-------|-------------|
| `GEMINI_API_KEY` | Your Google Gemini API key | https://aistudio.google.com/app/apikey |
| `INFRACOST_API_KEY` | Your Infracost API key (optional) | https://dashboard.infracost.io |

**Steps to add secrets:**
1. Go to your GitHub repository
2. Click **Settings** tab
3. Click **Secrets and variables** → **Actions**
4. Click **New repository secret**
5. Add `GEMINI_API_KEY` with your API key
6. Add `INFRACOST_API_KEY` if you have Infracost access

### 2. Verify Requirements File

Ensure `scripts/requirements.txt` exists with required packages:

```
google-genai
```

The workflow installs additional tools (checkov, infracost) automatically.

## 📊 Workflow Behavior

### Triggers

The workflow runs when:
- ✅ Pull requests modify files in `terraform/` folder
- ✅ Manually triggered via **Actions → Run workflow**
- ✅ Changes to the workflow file itself

### Workflow Steps

```
1. Checkout code
   ↓
2. Setup Python & install dependencies
   ↓
3. Run Checkov → Generate checkov-output.json
   ↓
4. Run Infracost → Generate infracost-output.json
   ↓
5. Run local.py → AI-powered analysis
   ↓
6. Post results to PR comment
   ↓
7. Upload artifacts
```

### Outputs

#### PR Comment
- Executive summary with merge recommendation
- Security findings and remediation steps
- Cost analysis and optimization opportunities

#### Artifacts (30-day retention)
- `checkov-output.json` - Raw security scan results
- `infracost-output.json` - Raw cost analysis results
- `infrastructure-analysis-report.md` - Formatted report (for PR)
- `infrastructure-analysis-report.json` - Complete structured data
- `infrastructure-analysis-summary.txt` - Brief text summary

## 🔧 Customization

### Change Trigger Paths
Edit the `on.pull_request.paths` section to trigger on different files:

```yaml
on:
  pull_request:
    paths:
      - 'terraform/**'        # Current: all terraform files
      - 'infrastructure/**'   # Alternative: other IaC tools
```

### Machine Type
Change `runs-on: ubuntu-latest` to use different runners:
- `ubuntu-latest` - Default Linux
- `ubuntu-22.04` - Specific Ubuntu version
- `self-hosted` - Your own runner

### Python Version
Edit the Python setup step if needed:

```yaml
python-version: '3.11'  # Change to 3.12, 3.10, etc.
```

## ⚙️ Using Without API Keys (Fallback)

If you don't have API keys:

- **Checkov works offline** ✅ - No key needed
- **Infracost limited** ⚠️ - Needs API key for accurate costs
- **Gemini AI skipped** ⚠️ - Needs API key for recommendations

The workflow won't fail, but you'll lose AI-powered insights.

## 📈 Example PR Comment Output

```
# Infrastructure Analysis Report

**Generated:** 2026-03-11 14:23:45

## Executive Summary

Overall Grade: B+ (Good security, moderate cost optimization needed)

PR Merge Decision: **✓ APPROVE WITH CONDITIONS**
- Fix open SSH access (Critical security blocker)
- Consider RDS right-sizing (Cost optimization)

## Security Analysis (Deep)

3 Critical findings, 8 High findings requiring remediation...

## Cost Analysis & Optimization (Deep)

Monthly cost: $4,250 (potential savings: $1,200/month)
Top optimization opportunities:
1. RDS downsizing: $525/month saved
2. Remove unused EBS volumes: $200/month saved
...
```

## 🐛 Troubleshooting

### Issue: Workflow doesn't trigger

**Solution:** Ensure Terraform files are modified in the PR
- Check the path filter: `paths: ['terraform/**']`
- Manually trigger: **Actions → Infrastructure Analysis & Risk Intelligence → Run workflow**

### Issue: "GEMINI_API_KEY not set"

**Solution:** Add the secret to GitHub
- Get key: https://aistudio.google.com/app/apikey
- Add to **Settings → Secrets and variables → Actions**
- Workflow will still run but skip AI analysis

### Issue: "Infracost not found"

**Solution:** This is normal
- Infracost installation is optional
- Security analysis (Checkov) still works
- Add `INFRACOST_API_KEY` secret to enable cost analysis

### Issue: PR comment doesn't appear

**Solution:** Check:
- Workflow has `pull-requests: write` permission ✅ (Already configured)
- Report was generated (check artifacts)
- GitHub token is valid

## 📚 Report Files

### infrastructure-analysis-report.md
- **Use for:** PR comments, documentation
- **Format:** Markdown with sections
- **Size:** ~10-100 KB typically

### infrastructure-analysis-report.json
- **Use for:** Parsing, automation, archiving
- **Format:** Structured JSON data
- **Size:** ~5-50 KB

### infrastructure-analysis-summary.txt
- **Use for:** Email notifications, dashboards
- **Format:** Plain text
- **Size:** ~1-5 KB

## 🔒 Security Notes

- API keys are encrypted in GitHub secrets
- Workflow has minimal permissions (read contents, write PR comments)
- Reports contain infrastructure details - consider artifact retention policies
- Private repositories: Reports are only visible to repo collaborators

## 📞 Support

For issues with:
- **Checkov**: https://www.checkov.io/
- **Infracost**: https://www.infracost.io/docs/
- **Gemini API**: https://ai.google.dev/
- **GitHub Actions**: https://docs.github.com/en/actions

## 🎯 Next Steps

1. ✅ Add GitHub secrets (Gemini API key required)
2. ✅ Verify `scripts/requirements.txt` exists
3. ✅ Create a test PR modifying `terraform/` files
4. ✅ Monitor the workflow run and check the PR comment
5. ✅ Adjust configuration as needed

---

**Created:** March 2026  
**Workflow File:** `.github/workflows/iac-analysis.yml`
