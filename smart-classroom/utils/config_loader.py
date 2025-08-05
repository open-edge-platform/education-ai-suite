import yaml
from types import SimpleNamespace
import os

def _dict_to_namespace(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in d.items()})
    return d

def load_config(path="config.yaml"):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return _dict_to_namespace(data)

# Load once and expose
config = load_config()
import yaml; print(yaml.dump(vars(config), sort_keys=False))
