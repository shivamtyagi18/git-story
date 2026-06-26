import argparse
import sys
import os
from typing import Optional

from .git_helper import GitHelper
from .parser import GitDiffParser
from .llm_summarizer import LLMSummarizer
from .renderer import Renderer

def main(args_list=None):
    parser = argparse.ArgumentParser(
        description="git-story: Interactive Git History & Architecture Evolution Generator"
    )
    parser.add_argument(
        "-p", "--path",
        default=".",
        help="Path to the git repository (default: current directory)"
    )
    parser.add_argument(
        "-r", "--revision-range",
        default=None,
        help="Git revision range (e.g. 'HEAD~10..HEAD' or 'v1.0..v2.0')"
    )
    parser.add_argument(
        "-n", "--max-commits",
        type=int,
        default=15,
        help="Max number of commits to process if no revision range is given (default: 15)"
    )
    parser.add_argument(
        "-o", "--output",
        default="git-story.html",
        help="Output HTML slide deck file name (default: git-story.html)"
    )
    parser.add_argument(
        "-t", "--api-type",
        choices=["ollama", "openai", "gemini", "fallback"],
        default="fallback",
        help="LLM API provider to use (default: fallback heuristic summarizer)"
    )
    parser.add_argument(
        "-u", "--api-url",
        default=None,
        help="Custom API URL for the LLM endpoint"
    )
    parser.add_argument(
        "-k", "--api-key",
        default=None,
        help="API Key (if not provided, reads OPENAI_API_KEY or GEMINI_API_KEY from environment)"
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="Model name (e.g. 'gpt-4o-mini', 'gemini-1.5-flash', 'llama3')"
    )

    args = parser.parse_args(args_list)

    print("🚀 Starting git-story...")
    
    # 1. Initialize GitHelper
    git_helper = GitHelper(args.path)
    if not git_helper.is_git_repo():
        print(f"❌ Error: Directory '{args.path}' is not a valid git repository.")
        sys.exit(1)
        
    print(f"📂 Target Repository: {git_helper.repo_path}")

    # 2. Get commits list
    try:
        commits = git_helper.get_commit_list(args.revision_range, args.max_commits)
    except Exception as e:
        print(f"❌ Error fetching commits: {str(e)}")
        sys.exit(1)

    if not commits:
        print("⚠️ No commits found matching criteria.")
        sys.exit(0)

    # Process commits chronologically (from oldest to newest) for architecture evolution
    commits.reverse()
    print(f"📈 Found {len(commits)} commits to process.")

    # 3. Setup Parser and Summarizer
    diff_parser = GitDiffParser(git_helper)
    summarizer = LLMSummarizer(
        api_type=args.api_type,
        api_url=args.api_url,
        api_key=args.api_key,
        model=args.model
    )

    summarized_commits = []
    
    print(f"🧠 Summarizer Mode: {summarizer.api_type} (Model: {summarizer.model or 'N/A'})")

    # 4. Parse & Summarize Loop
    for idx, commit in enumerate(commits, 1):
        print(f"🔄 [{idx}/{len(commits)}] Parsing & summarizing commit {commit['hash'][:8]}: {commit['subject'][:50]}...")
        
        parsed_data = diff_parser.parse_commit(commit)
        summary_data = summarizer.summarize_commit(parsed_data)
        
        summarized_commits.append(summary_data)

    # 5. Render to slide-deck
    print("🎨 Rendering interactive slide deck template...")
    renderer = Renderer()
    try:
        output_abs = renderer.render(summarized_commits, args.output)
        print(f"✨ Success! Saved interactive design history deck to:")
        print(f"   👉 file://{output_abs}")
    except Exception as e:
        print(f"❌ Rendering failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
