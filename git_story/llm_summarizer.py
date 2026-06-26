import json
import os
import requests
import re
from typing import Dict, Any, List

class LLMSummarizer:
    def __init__(self, api_type: str = "fallback", api_url: str = None, api_key: str = None, model: str = None):
        self.api_type = api_type.lower()
        self.api_url = api_url
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self.model = model

        # Set defaults based on api_type
        if self.api_type == "ollama":
            self.api_url = self.api_url or "http://localhost:11434/api/generate"
            self.model = self.model or "llama3"
        elif self.api_type == "openai":
            self.api_url = self.api_url or "https://api.openai.com/v1/chat/completions"
            self.model = self.model or "gpt-4o-mini"
        elif self.api_type == "gemini":
            self.api_url = self.api_url or "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            self.model = self.model or "gemini-1.5-flash"
            if not self.api_key:
                self.api_key = os.environ.get("GEMINI_API_KEY")

    def summarize_commit(self, commit_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Feeds the structured commit data to the LLM (or falls back to rules)
        to summarize architectural changes in a structured format.
        """
        # If fallback, or no keys/urls provided when required, run the local heuristic summarizer
        if self.api_type == "fallback" or (self.api_type in ["openai", "gemini"] and not self.api_key):
            return self._heuristic_summarize(commit_data)

        prompt = self._build_prompt(commit_data)
        
        try:
            if self.api_type == "ollama":
                response = self._call_ollama(prompt)
            else:  # openai or gemini (both use OpenAI-compatible completions format)
                response = self._call_openai_compatible(prompt)
                
            return self._parse_llm_response(response, commit_data)
        except Exception as e:
            # On any failure, degrade gracefully to the heuristic summarizer
            fallback_res = self._heuristic_summarize(commit_data)
            fallback_res["summary"] = f"[LLM Error: {str(e)[:60]}...] {fallback_res['summary']}"
            return fallback_res

    def _build_prompt(self, commit_data: Dict[str, Any]) -> str:
        # Build list of file descriptions
        file_descriptions = []
        for f in commit_data.get("files", []):
            desc = f"File: {f['filepath']}\nStatus: {f['status']}\nAdditions: {f['additions']}, Deletions: {f['deletions']}\nDiff Snippet:\n{f['diff_snippet']}\n"
            file_descriptions.append(desc)
            
        files_str = "\n".join(file_descriptions)
        
        prompt = f"""
You are a senior software architect. Analyze the following git commit diff and summarize its structural and architectural impact.
Ignore minor changes, refactoring styles, or documentation updates unless they redefine interfaces.
Focus on:
1. Decoupling of components (e.g., splitting a file, moving logic to a new module).
2. Database schema/migration changes.
3. API contract changes or public method signature changes.
4. Core design pattern implementations (e.g., adding a factory, observer, singleton, or manager).
5. New library dependencies.

Commit Subject: {commit_data['subject']}
Author: {commit_data['author']}
Date: {commit_data['date']}
Hash: {commit_data['hash']}

Files Changed & Diffs:
{files_str}

Format your response EXACTLY as a JSON object with the following fields:
{{
  "architectural_change": true or false,
  "summary": "A 1-sentence high-level summary of the architectural impact.",
  "impacted_components": ["component1", "component2"],
  "details": [
    {{
      "type": "decoupling | database-migration | interface-change | pattern-implementation | feature-addition | dependencies | other",
      "description": "Short explanation of the change.",
      "technical_details": "Classes, functions, or modules modified/added and why."
    }}
  ],
  "system_diagram_diff": {{
    "added_connections": [
      {{"from": "nodeA", "to": "nodeB"}}
    ],
    "removed_connections": [
      {{"from": "nodeC", "to": "nodeD"}}
    ]
  }}
}}

Provide ONLY the raw JSON. Do not write markdown blocks (like ```json), introduction, or conclusion.
"""
        return prompt

    def _call_ollama(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("response", "")

    def _call_openai_compatible(self, prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful software architecture assistant that only outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _parse_llm_response(self, text: str, commit_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parses the LLM's JSON output and returns a structured dictionary."""
        # Clean markdown code blocks if the LLM outputted them anyway
        cleaned_text = text.strip()
        if cleaned_text.startswith("```"):
            # Remove leading ```json or ```
            cleaned_text = re.sub(r"^```(?:json)?\n", "", cleaned_text)
            # Remove trailing ```
            cleaned_text = re.sub(r"\n```$", "", cleaned_text)
            
        try:
            result = json.loads(cleaned_text.strip())
            # Ensure required fields exist
            result["hash"] = commit_data["hash"]
            result["author"] = commit_data["author"]
            result["date"] = commit_data["date"]
            result["subject"] = commit_data["subject"]
            result["files"] = [f["filepath"] for f in commit_data.get("files", [])]
            return result
        except json.JSONDecodeError:
            # If JSON parsing fails, build a structured dict using a fallback summary
            fallback = self._heuristic_summarize(commit_data)
            fallback["summary"] = f"[LLM Parse Error] {commit_data['subject']}"
            fallback["raw_llm_output"] = text
            return fallback

    def _heuristic_summarize(self, commit_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        A local rule-based heuristic summarizer that acts as a fallback when
        no LLM is configured or when the LLM request fails.
        """
        subject = commit_data["subject"]
        files = commit_data.get("files", [])
        
        impacted_components = set()
        details = []
        is_arch = False
        
        # Categorize based on file extensions/paths
        for f in files:
            path = f["filepath"]
            status = f["status"]
            
            # Simple component resolution based on directories
            dir_parts = path.split("/")
            if len(dir_parts) > 1:
                impacted_components.add(dir_parts[0])
            else:
                impacted_components.add("root")
                
            # Heuristics for database/migrations
            if "migrate" in path.lower() or "schema" in path.lower() or path.endswith(".sql"):
                is_arch = True
                details.append({
                    "type": "database-migration",
                    "description": f"Database file '{os.path.basename(path)}' was {status}.",
                    "technical_details": f"Detected migration/schema change in {path}."
                })
                
            # Heuristics for dependencies
            elif path in ["requirements.txt", "package.json", "setup.py", "pyproject.toml", "Gemfile", "Cargo.toml"]:
                is_arch = True
                details.append({
                    "type": "dependencies",
                    "description": f"Dependency manifest '{path}' was updated.",
                    "technical_details": f"Added or modified external libraries."
                })
                
            # Heuristics for interfaces/contracts
            elif "interface" in path.lower() or "abstract" in path.lower() or "proto" in path.lower():
                is_arch = True
                details.append({
                    "type": "interface-change",
                    "description": f"Interface/contract file '{os.path.basename(path)}' was {status}.",
                    "technical_details": f"Public API definition changed in {path}."
                })
                
            # Decoupling or pattern addition
            elif status == "added" and len(files) > 2:
                is_arch = True
                details.append({
                    "type": "decoupling",
                    "description": f"New component file '{os.path.basename(path)}' was added.",
                    "technical_details": f"Structural expansion: created {path}."
                })

        # Add general feature addition if details is empty
        if not details:
            details.append({
                "type": "feature-addition",
                "description": f"Implemented changes in {len(files)} files.",
                "technical_details": f"Modified files: {', '.join([os.path.basename(f['filepath']) for f in files[:3]])}"
            })
            
        # Determine if architectural
        if not is_arch:
            # Check commit subject keywords
            keywords = ["refactor", "architect", "rewrite", "split", "decouple", "design", "migrate", "api", "interface"]
            if any(kw in subject.lower() for kw in keywords):
                is_arch = True

        return {
            "hash": commit_data["hash"],
            "author": commit_data["author"],
            "date": commit_data["date"],
            "subject": subject,
            "architectural_change": is_arch,
            "summary": f"Local analysis: {subject}",
            "impacted_components": list(impacted_components) if impacted_components else ["system"],
            "details": details,
            "system_diagram_diff": {
                "added_connections": [],
                "removed_connections": []
            },
            "files": [f["filepath"] for f in files]
        }
