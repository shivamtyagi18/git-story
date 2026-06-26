import subprocess
import os
from typing import List, Dict, Optional

class GitHelper:
    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)

    def run_git(self, args: List[str]) -> str:
        """Helper to run a git command inside the repository path."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {' '.join(e.cmd)}\nError: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError("Git executable not found. Please ensure git is installed and on your PATH.")

    def is_git_repo(self) -> bool:
        """Check if the path is a valid git repository."""
        if not os.path.exists(self.repo_path):
            return False
        try:
            self.run_git(["rev-parse", "--is-inside-work-tree"])
            return True
        except Exception:
            return False

    def get_commit_list(self, revision_range: Optional[str] = None, max_commits: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get the list of commits.
        Returns a list of dicts: {'hash': ..., 'author': ..., 'date': ..., 'subject': ...}
        """
        # Format string: hash|author|date|subject
        format_str = "%H|%an|%ad|%s"
        args = ["log", f"--pretty=format:{format_str}", "--date=iso-strict"]
        
        if revision_range:
            args.append(revision_range)
        elif max_commits:
            args.extend(["-n", str(max_commits)])
            
        try:
            log_output = self.run_git(args)
        except Exception as e:
            # If revision range failed, fallback or raise
            raise RuntimeError(f"Failed to fetch git log with range '{revision_range}': {str(e)}")

        commits = []
        if not log_output:
            return commits

        for line in log_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "subject": parts[3]
                })
        return commits

    def get_commit_diff(self, commit_hash: str) -> str:
        """Get the full diff for a specific commit hash."""
        return self.run_git(["show", commit_hash])

    def get_commit_stat(self, commit_hash: str) -> str:
        """Get the file-change stats for a specific commit hash."""
        return self.run_git(["show", "--stat", commit_hash])

    def get_diff_between(self, start_ref: str, end_ref: str) -> str:
        """Get the diff between two references/commits."""
        return self.run_git(["diff", f"{start_ref}..{end_ref}"])
