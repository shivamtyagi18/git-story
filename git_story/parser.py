import re
from typing import List, Dict, Any, Tuple
from .git_helper import GitHelper

class GitDiffParser:
    def __init__(self, git_helper: GitHelper):
        self.git_helper = git_helper
        # Exclude files that do not reflect architectural/code structure changes
        self.ignored_patterns = [
            r"\.lock$", r"package-lock\.json$", r"yarn\.lock$", r"pnpm-lock\.yaml$",
            r"\.png$", r"\.jpg$", r"\.jpeg$", r"\.gif$", r"\.svg$", r"\.ico$",
            r"\.pdf$", r"\.zip$", r"\.tar\.gz$", r"\.mp3$", r"\.mp4$",
            r"\.csv$", r"\.json$", r"\.tsv$", r"\.yaml$", r"\.yml$", # config files, though some yaml might be CI/CD
            r"node_modules/", r"vendor/", r"dist/", r"build/", r"\.git/"
        ]

    def should_ignore(self, filepath: str) -> bool:
        """Return True if the filepath matches any ignored pattern."""
        for pattern in self.ignored_patterns:
            if re.search(pattern, filepath, re.IGNORECASE):
                return True
        return False

    def parse_commit(self, commit: Dict[str, str]) -> Dict[str, Any]:
        """
        Parses a commit: retrieves the stat and raw diff, filters out noise,
        and constructs a structured payload ready for the LLM.
        """
        commit_hash = commit["hash"]
        
        # Get raw diff and stats
        try:
            stat_output = self.git_helper.get_commit_stat(commit_hash)
            raw_diff = self.git_helper.get_commit_diff(commit_hash)
        except Exception as e:
            return {
                "hash": commit_hash,
                "author": commit["author"],
                "date": commit["date"],
                "subject": commit["subject"],
                "error": f"Failed to retrieve diff: {str(e)}",
                "files": []
            }

        # Parse stats to count additions/deletions per file
        # Format of git show --stat line is typically:
        #  path/to/file.py | 12 +++++---
        #  1 file changed, 8 insertions(+), 4 deletions(-)
        file_stats = self._parse_stat_output(stat_output)
        
        # Parse raw diff into separate files and their diff snippets
        parsed_files = self._parse_raw_diff(raw_diff)
        
        # Filter files and merge stat info
        filtered_files = []
        for file_info in parsed_files:
            filepath = file_info["filepath"]
            if self.should_ignore(filepath):
                continue
                
            stats = file_stats.get(filepath, {"additions": 0, "deletions": 0})
            file_info["additions"] = stats["additions"]
            file_info["deletions"] = stats["deletions"]
            
            # Truncate large diff snippets to keep LLM context reasonable
            file_info["diff_snippet"] = self._truncate_diff(file_info["diff_snippet"])
            filtered_files.append(file_info)

        return {
            "hash": commit_hash,
            "author": commit["author"],
            "date": commit["date"],
            "subject": commit["subject"],
            "files": filtered_files
        }

    def _parse_stat_output(self, stat_output: str) -> Dict[str, Dict[str, int]]:
        """Parses git show --stat output to extract additions and deletions per file."""
        stats = {}
        # We look for lines like: " path/to/file.py | 12 +++++--- "
        # Or renames like: " src/{a => b}/file.py | 4 +-- "
        pattern = re.compile(r"^\s+(?P<file>.+?)\s+\|\s+(?P<num>\d+)\s+(?P<sign>[+-]*)$")
        
        for line in stat_output.split("\n"):
            match = pattern.match(line)
            if match:
                filepath = match.group("file").strip()
                # Clean up rename syntax e.g., "src/{a => b}/file.py" to just "src/b/file.py"
                filepath = self._clean_rename_filepath(filepath)
                
                sign = match.group("sign")
                additions = sign.count("+")
                deletions = sign.count("-")
                
                # If there's no visual +/-, check the number of changes
                total_changes = int(match.group("num"))
                if total_changes > 0 and additions == 0 and deletions == 0:
                    # Occurs if binary or just count given without signs
                    additions = total_changes
                    
                stats[filepath] = {"additions": additions, "deletions": deletions}
        return stats

    def _clean_rename_filepath(self, filepath: str) -> str:
        """Cleans rename syntax like 'dir/{old => new}/file.txt' or 'old => new'."""
        if " => " not in filepath:
            return filepath
            
        # Case 1: dir/{old => new}/file.txt
        match = re.search(r"^(.*?)\{(.*?) => (.*?)\}(.*?)$", filepath)
        if match:
            prefix, _, new, suffix = match.groups()
            return f"{prefix}{new}{suffix}".replace("//", "/")
            
        # Case 2: old => new
        parts = filepath.split(" => ")
        if len(parts) == 2:
            return parts[1]
            
        return filepath

    def _parse_raw_diff(self, raw_diff: str) -> List[Dict[str, Any]]:
        """Parses raw git diff into a list of files with their filepath, status, and diff body."""
        files = []
        current_file = None
        diff_lines = []
        
        # Git diff lines look like:
        # diff --git a/src/main.py b/src/main.py
        # new file mode 100644
        # index 0000000..1234567
        # --- a/src/main.py
        # +++ b/src/main.py
        # @@ -1,3 +1,4 @@
        # ...
        
        diff_header_pattern = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
        
        for line in raw_diff.split("\n"):
            header_match = diff_header_pattern.match(line)
            if header_match:
                # Save previous file
                if current_file:
                    current_file["diff_snippet"] = "\n".join(diff_lines)
                    files.append(current_file)
                    diff_lines = []
                
                # Setup new file
                old_path, new_path = header_match.groups()
                status = "modified"
                if old_path == "/dev/null" or line.startswith("new file"):
                    status = "added"
                elif new_path == "/dev/null" or line.startswith("deleted file"):
                    status = "deleted"
                    
                current_file = {
                    "filepath": new_path if new_path != "/dev/null" else old_path,
                    "status": status,
                    "diff_snippet": ""
                }
            elif current_file:
                # Record the line if it is not git diff boilerplates (like index or mode lines)
                if not (line.startswith("index ") or line.startswith("new file mode") or line.startswith("deleted file mode")):
                    diff_lines.append(line)
                    
        # Append last file
        if current_file:
            current_file["diff_snippet"] = "\n".join(diff_lines)
            files.append(current_file)
            
        return files

    def _truncate_diff(self, diff_snippet: str, max_lines: int = 60, max_chars: int = 3000) -> str:
        """Truncates diff content to keep prompts concise, leaving structure intact."""
        lines = diff_snippet.split("\n")
        if len(lines) <= max_lines and len(diff_snippet) <= max_chars:
            return diff_snippet
            
        truncated_lines = []
        # Keep the header info (usually first 4 lines: ---, +++, @@)
        header_limit = min(5, len(lines))
        truncated_lines.extend(lines[:header_limit])
        
        # Add a note
        truncated_lines.append(f"\n... [Diff truncated: {len(lines) - header_limit} lines omitted] ...\n")
        
        # Add a mix of tail or just keep it simple with header + middle snippets
        # Let's keep first 30 lines and last 15 lines of the diff if available
        remaining_lines = lines[header_limit:]
        if len(remaining_lines) > 40:
            truncated_lines.extend(remaining_lines[:25])
            truncated_lines.append("\n... [Skipped lines] ...\n")
            truncated_lines.extend(remaining_lines[-15:])
        else:
            truncated_lines.extend(remaining_lines[:max_lines - header_limit])
            
        res = "\n".join(truncated_lines)
        if len(res) > max_chars:
            res = res[:max_chars] + "\n... [Diff truncated due to size] ..."
        return res
