import os
from github import Github, Auth  

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PR_NUMBER = os.getenv("PR_NUMBER")
REPO_NAME = os.getenv("GITHUB_REPOSITORY")


auth = Auth.Token(GITHUB_TOKEN)
g = Github(auth=auth)

repo = g.get_repo(REPO_NAME)
pr = repo.get_pull(int(PR_NUMBER))

with open("ai_review.txt") as f:
    review = f.read()

comment = f"""
## Terraform Security Review  

{review}
"""

pr.create_issue_comment(comment)