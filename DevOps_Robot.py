#!/usr/bin/env python3
"""
AI DevOps Robot - Automated GitHub and Deployment Manager
Fully functional: GitHub ops + Vercel/Netlify/Render deploy hooks + GitHub Actions
"""

import os
import json
import time
import requests
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _safe_json(res: requests.Response):
    try:
        return res.json()
    except Exception:
        return {"text": res.text, "status": res.status_code}


def _print_err(prefix: str, res: requests.Response):
    data = _safe_json(res)
    print(f"❌ {prefix} (HTTP {res.status_code}): {data}")


class AIDevOpsRobot:
    def __init__(self, config_file: str = "devops_config.yaml"):
        """Initialize the AI DevOps Robot with configuration"""
        self.config = self.load_config(config_file)
        # Prefer environment variables; fall back to config
        self.github_token = os.getenv("GITHUB_TOKEN") or self.config.get("github_token")
        self.github_username = (
            os.getenv("GITHUB_USERNAME") or self.config.get("github_username")
        )
        if not self.github_username:
            raise ValueError("Missing github_username (set in .env or devops_config.yaml)")

        self.base_headers = {
            "Authorization": f"token {self.github_token}" if self.github_token else "",
            "Accept": "application/vnd.github.v3+json",
        }

    # ---------------------------
    # Config
    # ---------------------------
    def load_config(self, config_file: str) -> Dict:
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            print(f"Config file {config_file} not found. Creating default config...")
            self.create_default_config(config_file)
            return {}

    def create_default_config(self, config_file: str):
        default_config = {
            "github_username": "your_github_username",
            "default_branch": "main",
            "auto_deploy": True,
            "hosting_platforms": {
                "vercel": {
                    "enabled": False,
                    "deploy_hook_url": ""  # Use a Vercel Deploy Hook URL
                },
                "render": {
                    "enabled": False,
                    "service_id": ""  # Render service id
                },
                "netlify": {
                    "enabled": False,
                    "deploy_hook_url": ""  # Netlify build hook URL
                },
            },
            "commit_message_templates": [
                "🚀 Auto-deploy: {description}",
                "📝 Update: {description}",
                "🔧 Fix: {description}",
                "✨ Feature: {description}",
            ],
        }
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, default_flow_style=False)
        print(f"Default config created at {config_file}")

    # ---------------------------
    # Git helpers
    # ---------------------------
    def _ensure_git_identity(self, repo_path: str):
        # Ensure user.name and user.email exist to allow commits
        try:
            name = subprocess.run(
                ["git", "config", "user.name"], cwd=repo_path, capture_output=True, text=True
            )
            email = subprocess.run(
                ["git", "config", "user.email"], cwd=repo_path, capture_output=True, text=True
            )
            if not name.stdout.strip():
                subprocess.run(
                    ["git", "config", "user.name", "AI DevOps Robot"],
                    cwd=repo_path,
                    check=True,
                )
            if not email.stdout.strip():
                # Use GitHub no-reply style; replace with your own if desired
                noreply = f"{self.github_username}@users.noreply.github.com"
                subprocess.run(
                    ["git", "config", "user.email", noreply],
                    cwd=repo_path,
                    check=True,
                )
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Could not ensure git identity: {e}")

    def get_default_branch(self, repo_name: str) -> str:
        # Try API, fall back to config then 'main'
        if self.github_token:
            url = f"https://api.github.com/repos/{self.github_username}/{repo_name}"
            res = requests.get(url, headers=self.base_headers)
            if res.status_code == 200:
                return res.json().get("default_branch", "main")
        return self.config.get("default_branch", "main")

    # ---------------------------
    # GitHub Operations
    # ---------------------------
    def create_repository(self, repo_name: str, description: str = "", private: bool = False) -> Dict:
        if not self.github_token:
            raise ValueError("Missing GITHUB_TOKEN for GitHub API calls.")
        url = "https://api.github.com/user/repos"
        data = {
            "name": repo_name,
            "description": description,
            "private": private,
            "auto_init": True,
        }
        res = requests.post(url, headers=self.base_headers, json=data)
        if res.status_code == 201:
            repo_data = res.json()
            print(f"✅ Repository '{repo_name}' created: {repo_data.get('html_url')}")
            return repo_data
        _print_err("Failed to create repository", res)
        return {}

    def clone_repository(self, repo_name: str, local_path: Optional[str] = None) -> str:
        if not local_path:
            local_path = f"./{repo_name}"
        repo_url = f"https://github.com/{self.github_username}/{repo_name}.git"
        try:
            subprocess.run(["git", "clone", repo_url, local_path], check=True)
            print(f"✅ Repository cloned to {local_path}")
            return local_path
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to clone repository {repo_name}: {e}")
            return ""

    def commit_and_push(self, repo_path: str, message: Optional[str] = None, files: Optional[List[str]] = None, branch: Optional[str] = None):
        self._ensure_git_identity(repo_path)
        if not branch:
            # Try to infer current branch
            try:
                cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, capture_output=True, text=True, check=True)
                branch = cur.stdout.strip() or "main"
            except subprocess.CalledProcessError:
                branch = "main"

        try:
            if files:
                for file in files:
                    subprocess.run(["git", "add", file], cwd=repo_path, check=True)
            else:
                subprocess.run(["git", "add", "."], cwd=repo_path, check=True)

            if not message:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                message = f"🤖 Auto-commit: Updated files at {timestamp}"

            subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)
            subprocess.run(["git", "push", "origin", branch], cwd=repo_path, check=True)
            print(f"✅ Changes committed and pushed to {branch}: {message}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Git operation failed: {e}")

    def create_pull_request(self, repo_name: str, title: str, body: str, head_branch: str, base_branch: str = "main") -> Dict:
        if not self.github_token:
            raise ValueError("Missing GITHUB_TOKEN for GitHub API calls.")
        url = f"https://api.github.com/repos/{self.github_username}/{repo_name}/pulls"
        data = {"title": title, "body": body, "head": head_branch, "base": base_branch}
        res = requests.post(url, headers=self.base_headers, json=data)
        if res.status_code == 201:
            pr_data = res.json()
            print(f"✅ Pull request created: #{pr_data['number']}")
            return pr_data
        _print_err("Failed to create pull request", res)
        return {}

    def merge_pull_request(self, repo_name: str, pr_number: int, merge_method: str = "merge") -> bool:
        if not self.github_token:
            raise ValueError("Missing GITHUB_TOKEN for GitHub API calls.")
        url = f"https://api.github.com/repos/{self.github_username}/{repo_name}/pulls/{pr_number}/merge"
        res = requests.put(url, headers=self.base_headers, json={"merge_method": merge_method})
        if res.status_code == 200:
            print(f"✅ Pull request #{pr_number} merged successfully!")
            return True
        _print_err("Failed to merge pull request", res)
        return False

    # ---------------------------
    # Deployment (Hooks-first)
    # ---------------------------
    def deploy_to_vercel(self, repo_name: str) -> bool:
        cfg = self.config.get("hosting_platforms", {}).get("vercel", {})
        if not cfg.get("enabled"):
            print("⚠️ Vercel deployment not enabled in config")
            return False
        hook = cfg.get("deploy_hook_url")
        if not hook:
            print("❌ Missing vercel.deploy_hook_url in config (use a Vercel Deploy Hook).")
            return False
        try:
            res = requests.post(hook)
            if res.status_code in (200, 201, 202):
                print("✅ Vercel deployment triggered!")
                return True
            _print_err("Vercel deployment failed", res)
            return False
        except requests.RequestException as e:
            print(f"❌ Vercel request error: {e}")
            return False

    def deploy_to_render(self, service_id: Optional[str] = None) -> bool:
        cfg = self.config.get("hosting_platforms", {}).get("render", {})
        if not cfg.get("enabled"):
            print("⚠️ Render deployment not enabled in config")
            return False
        render_token = os.getenv("RENDER_TOKEN")
        if not render_token:
            print("❌ RENDER_TOKEN is not set (.env)")
            return False
        service_id = service_id or cfg.get("service_id")
        if not service_id:
            print("❌ Missing render.service_id in config")
            return False
        url = f"https://api.render.com/v1/services/{service_id}/deploys"
        headers = {"Authorization": f"Bearer {render_token}", "Content-Type": "application/json"}
        res = requests.post(url, headers=headers)
        if res.status_code in (200, 201, 202):
            print("✅ Render deployment triggered!")
            return True
        _print_err("Render deployment failed", res)
        return False

    def deploy_to_netlify(self) -> bool:
        cfg = self.config.get("hosting_platforms", {}).get("netlify", {})
        if not cfg.get("enabled"):
            print("⚠️ Netlify deployment not enabled in config")
            return False
        hook = cfg.get("deploy_hook_url")
        if hook:
            try:
                res = requests.post(hook)
                if res.status_code in (200, 201, 202):
                    print("✅ Netlify deployment (build hook) triggered!")
                    return True
                _print_err("Netlify deployment failed", res)
                return False
            except requests.RequestException as e:
                print(f"❌ Netlify request error: {e}")
                return False
        print("❌ Missing netlify.deploy_hook_url in config (use a Netlify Build Hook).")
        return False

    # ---------------------------
    # Automation
    # ---------------------------
    def auto_workflow_update_and_deploy(self, repo_name: str, files_to_update: Dict[str, str]):
        print(f"🤖 Starting automated workflow for {repo_name}")
        repo_path = f"./{repo_name}"
        if not os.path.exists(repo_path):
            repo_path = self.clone_repository(repo_name)
        if not repo_path:
            return False

        for file_path, content in files_to_update.items():
            full_path = os.path.join(repo_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"📝 Updated {file_path}")

        commit_msg = f"🤖 Auto-update: {len(files_to_update)} files updated"
        self.commit_and_push(repo_path, commit_msg)

        if self.config.get("auto_deploy", True):
            self.trigger_all_deployments(repo_name)
        return True

    def trigger_all_deployments(self, repo_name: str):
        platforms = self.config.get("hosting_platforms", {})
        ok_any = False
        if platforms.get("vercel", {}).get("enabled"):
            ok_any = self.deploy_to_vercel(repo_name) or ok_any
        if platforms.get("render", {}).get("enabled"):
            ok_any = self.deploy_to_render(platforms["render"].get("service_id")) or ok_any
        if platforms.get("netlify", {}).get("enabled"):
            ok_any = self.deploy_to_netlify() or ok_any
        if not ok_any:
            print("ℹ️ No deployments triggered (check config).")

    # ---------------------------
    # Repo quality helpers
    # ---------------------------
    def analyze_repository(self, repo_name: str) -> Dict:
        url = f"https://api.github.com/repos/{self.github_username}/{repo_name}/contents"
        res = requests.get(url, headers=self.base_headers)
        if res.status_code != 200:
            _print_err("Failed to analyze repository", res)
            return {}
        files = res.json()
        analysis = {
            "files": [f["name"] for f in files],
            "has_readme": any(f["name"].lower().startswith("readme") for f in files),
            "has_package_json": any(f["name"] == "package.json" for f in files),
            "has_dockerfile": any(f["name"].lower() == "dockerfile" for f in files),
            "suggestions": [],
        }
        if not analysis["has_readme"]:
            analysis["suggestions"].append("Add a README.md file")
        if not analysis["has_package_json"] and any(".js" in f["name"] for f in files):
            analysis["suggestions"].append("Consider adding package.json for Node.js project")
        return analysis

    def auto_improve_repository(self, repo_name: str):
        analysis = self.analyze_repository(repo_name)
        if not analysis:
            return False
        improvements: Dict[str, str] = {}

        if not analysis["has_readme"]:
            improvements["README.md"] = self.generate_readme(repo_name)
        if ".gitignore" not in analysis["files"]:
            improvements[".gitignore"] = self.generate_gitignore()

        # Always ensure a minimal deploy workflow exists
        improvements[".github/workflows/deploy.yml"] = self.generate_github_actions_workflow(
            ["vercel", "render", "netlify"]
        )

        if improvements:
            self.auto_workflow_update_and_deploy(repo_name, improvements)
            print(f"🚀 Repository {repo_name} improved with {len(improvements)} files")
            return True
        print("ℹ️ No improvements needed.")
        return True

    # ---------------------------
    # Generators
    # ---------------------------
    def generate_readme(self, repo_name: str) -> str:
        return f"""# {repo_name}

## Description
This project is managed by **AI DevOps Robot**.

## Features
- GitHub automation (create repo, commit, PR/merge)
- One-click deployments via deploy hooks:
  - Vercel
  - Render
  - Netlify

## Quick Start
1. Create `.env` (see `.env.example`) and `devops_config.yaml`.
2. `pip install -r requirements.txt`
3. Run: `python devops_robot.py`
4. Use commands like `create_repo`, `improve_repo`, `deploy`.

## License
MIT
"""

    def generate_gitignore(self) -> str:
        return """# Dependencies
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Environment
.env
.env.*

# Build outputs
dist/
build/
.next/
out/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Logs
logs
*.log

# Coverage
coverage/

# Cache
.cache/
.parcel-cache/
"""

    def generate_github_actions_workflow(self, platforms: List[str]) -> str:
        # Minimal, hook-based deploys (works for any project type)
        return """name: Deploy (Hooks)

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Vercel (if configured)
        if: ${{ secrets.VERCEL_DEPLOY_HOOK != '' }}
        run: curl -X POST "${{ secrets.VERCEL_DEPLOY_HOOK }}"

      - name: Trigger Render (if configured)
        if: ${{ secrets.RENDER_SERVICE_ID != '' && secrets.RENDER_TOKEN != '' }}
        run: |
          curl -X POST "https://api.render.com/v1/services/${{ secrets.RENDER_SERVICE_ID }}/deploys" \
          -H "Authorization: Bearer ${{ secrets.RENDER_TOKEN }}"

      - name: Trigger Netlify (if configured)
        if: ${{ secrets.NETLIFY_BUILD_HOOK != '' }}
        run: curl -X POST "${{ secrets.NETLIFY_BUILD_HOOK }}"
"""

    # ---------------------------
    # Batch + PR review + Health
    # ---------------------------
    def batch_repository_operation(self, repos: List[str], operation: str, **kwargs):
        results = []
        for repo in repos:
            print(f"🔄 Processing {repo}...")
            ok = False
            if operation == "update_and_deploy":
                ok = self.auto_workflow_update_and_deploy(repo, kwargs.get("files", {}))
            elif operation == "improve":
                ok = self.auto_improve_repository(repo)
            elif operation == "deploy":
                self.trigger_all_deployments(repo)
                ok = True
            else:
                print(f"❌ Unknown operation: {operation}")
            results.append({"repo": repo, "success": ok})
            time.sleep(1.2)
        return results

    def check_deployment_status(self, repo_name: str) -> Dict:
        status = {}
        if not self.github_token:
            return status
        url = f"https://api.github.com/repos/{self.github_username}/{repo_name}/actions/runs"
        res = requests.get(url, headers=self.base_headers)
        if res.status_code == 200:
            runs = res.json().get("workflow_runs", [])
            if runs:
                latest = runs[0]
                status["github_actions"] = {
                    "status": latest.get("status"),
                    "conclusion": latest.get("conclusion"),
                    "updated_at": latest.get("updated_at"),
                }
        return status

    def health_check_all_repos(self) -> Dict:
        if not self.github_token:
            print("⚠️ No GITHUB_TOKEN: skipping health check.")
            return {}
        url = f"https://api.github.com/users/{self.github_username}/repos"
        res = requests.get(url, headers=self.base_headers)
        if res.status_code != 200:
            _print_err("Failed to list repositories", res)
            return {}
        repos = res.json()
        report = {}
        for repo in repos:
            report[repo["name"]] = {
                "last_updated": repo["updated_at"],
                "has_issues": repo["open_issues_count"] > 0,
                "is_private": repo["private"],
                "default_branch": repo["default_branch"],
            }
        return report

    def smart_commit_message(self, changed_files: List[str]) -> str:
        file_types = {}
        for file in changed_files:
            ext = Path(file).suffix.lower()
            file_types[ext] = file_types.get(ext, 0) + 1
        if ".py" in file_types:
            return f"🐍 Update Python files ({file_types['.py']} files)"
        if ".js" in file_types or ".ts" in file_types:
            total = file_types.get(".js", 0) + file_types.get(".ts", 0)
            return f"📦 Update JavaScript/TypeScript ({total} files)"
        if ".md" in file_types:
            return f"📝 Update documentation ({file_types['.md']} files)"
        if ".css" in file_types or ".scss" in file_types:
            total = file_types.get(".css", 0) + file_types.get(".scss", 0)
            return f"🎨 Update styles ({total} files)"
        return f"🔧 Update {len(changed_files)} files"

    def auto_pr_review(self, repo_name: str, pr_number: int) -> Dict:
        if not self.github_token:
            raise ValueError("Missing GITHUB_TOKEN for GitHub API calls.")
        url = f"https://api.github.com/repos/{self.github_username}/{repo_name}/pulls/{pr_number}/files"
        res = requests.get(url, headers=self.base_headers)
        if res.status_code != 200:
            _print_err("Failed to fetch PR files", res)
            return {}
        files = res.json()
        review = {"suggestions": [], "warnings": [], "approvals": []}
        for file in files:
            filename = file["filename"]
            patch = file.get("patch", "") or ""
            if filename.endswith(".js") and "console.log" in patch:
                review["warnings"].append(f"Console.log found in {filename}")
            if filename.endswith(".py") and "print(" in patch:
                review["suggestions"].append(f"Use logging instead of print in {filename}")
            if file.get("additions", 0) > 500:
                review["warnings"].append(f"Large change in {filename} ({file['additions']} additions)")
        return review


def main():
    robot = AIDevOpsRobot()
    print("🤖 AI DevOps Robot Started")
    print("Commands:")
    print("  create_repo <name> <description>")
    print("  improve_repo <name>")
    print("  deploy <name>")
    print("  batch_improve <repo1,repo2,repo3>")
    print("  health_check")
    print("  quit")
    while True:
        try:
            command = input("\n🤖 Enter command: ").strip().split()
            if not command:
                continue
            if command[0] == "quit":
                print("👋 AI DevOps Robot shutting down...")
                break
            elif command[0] == "create_repo" and len(command) >= 2:
                repo_name = command[1]
                description = " ".join(command[2:]) if len(command) > 2 else ""
                robot.create_repository(repo_name, description)
            elif command[0] == "improve_repo" and len(command) >= 2:
                repo_name = command[1]
                robot.auto_improve_repository(repo_name)
            elif command[0] == "deploy" and len(command) >= 2:
                repo_name = command[1]
                robot.trigger_all_deployments(repo_name)
            elif command[0] == "batch_improve" and len(command) >= 2:
                repos = command[1].split(",")
                robot.batch_repository_operation(repos, "improve")
            elif command[0] == "health_check":
                health = robot.health_check_all_repos()
                print("\n📊 Repository Health Report:")
                for repo, status in health.items():
                    mark = "🟢" if not status.get("has_issues") else "🟡"
                    print(f"  {repo}: {mark} (updated {status.get('last_updated')})")
            else:
                print("❌ Invalid command or missing parameters")
        except KeyboardInterrupt:
            print("\n👋 AI DevOps Robot shutting down...")
            break
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
