"""Full distribution metadata; the only version source is in the core project."""
import ast
from pathlib import Path
from setuptools import setup

root = Path(__file__).parent
version_file = root / 'core/mcpywrap_core/_version.py'
version = ast.literal_eval(ast.parse(version_file.read_text()).body[0].value)
setup(version=version, install_requires=[
    'mcpywrap-core==' + version,
    'pip>=23', 'build>=1.0', 'watchdog>=2.0.0', 'twine>=3.4.0', 'setuptools',
    'jsonschema>=4.18,<5', 'psutil>=5.8.0', 'rich>=10.0.0',
    "capstone>=5,<6; sys_platform == 'win32'",
    "pefile>=2023; sys_platform == 'win32'",
    "PySide6-Essentials>=6.6,<7; sys_platform == 'win32' or sys_platform == 'darwin'",
])
