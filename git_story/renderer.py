import json
import os
from jinja2 import Template
from typing import List, Dict, Any

class Renderer:
    def __init__(self, template_path: str = None):
        if not template_path:
            # Resolve default template relative to this file
            template_path = os.path.join(os.path.dirname(__file__), "templates", "slide_deck.html")
        self.template_path = template_path

    def render(self, commits: List[Dict[str, Any]], output_path: str):
        """
        Renders the structured commits data to an interactive HTML slide-deck.
        Injects the data directly into the Jinja2 template and writes it to output_path.
        """
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template slide-deck file not found at: {self.template_path}")

        with open(self.template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        template = Template(template_content)
        
        # Serialize the commits list to a JSON string for JavaScript insertion
        commits_json = json.dumps(commits, indent=2)
        
        rendered_html = template.render(commits_json=commits_json)
        
        # Ensure output folder exists
        output_dir = os.path.dirname(os.path.abspath(output_path))
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(rendered_html)
            
        return os.path.abspath(output_path)
