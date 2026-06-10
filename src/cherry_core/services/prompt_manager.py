import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.cherry_core.config import PROMPTS_DIR

class PromptManager:
    """
    Manages loading and rendering of investigation prompts.
    Uses Jinja2 for templates and YAML for scenario data.
    Standardized for Clean Architecture.
    """
    def __init__(self):
        # Resolve absolute path to prompts directory
        self.base_dir = PROMPTS_DIR

        # Include both base_dir and templates/ to allow {% include 'modules/...' %}
        self.env = Environment(loader=FileSystemLoader([str(self.base_dir / "templates"), str(self.base_dir)]))

    def load_scenario(self, scenario_name: str) -> dict:
        """Load static data from a scenario YAML file."""
        yaml_path = self.base_dir / "scenarios" / f"{scenario_name}.yaml"
        if not yaml_path.exists():
            return {}
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def render_prompt(self, template_name: str, transcript: str, scenario: str = None) -> str:
        """
        Render a final prompt for the LLM.
        """
        template = self.env.get_template(template_name)

        context_data = {"transcript": transcript}

        # Inject scenario data if provided
        if scenario:
            scenario_data = self.load_scenario(scenario)
            context_data.update(scenario_data)

        return template.render(**context_data)
