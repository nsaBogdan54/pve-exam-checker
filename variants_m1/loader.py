import os
import glob
import importlib.util

VARIANTS_DIR = os.path.dirname(os.path.abspath(__file__))


def list_variants():
    files = sorted(glob.glob(os.path.join(VARIANTS_DIR, "*.py")))
    names = [
        os.path.splitext(os.path.basename(f))[0]
        for f in files
        if os.path.basename(f) not in ("__init__.py", "loader.py")
    ]
    return names or ["default"]


def load_variant(name=None):
    names = list_variants()
    if not name or name not in names:
        name = "default" if "default" in names else names[0]
    path = os.path.join(VARIANTS_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"variant_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._VARIANT_NAME = name
    return mod
