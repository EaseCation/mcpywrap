"""Ship the canonical skill with both wheel and source installations."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent

def skill_source():
    bundled = ROOT/'mcpywrap_core/skill'
    return bundled if bundled.is_dir() else ROOT.parent/'skills/mcpywrap'

class BuildPy(build_py):
    def run(self):
        super().run()
        source = skill_source()
        if not (source/'SKILL.md').is_file(): raise RuntimeError('Canonical mcpywrap skill is missing')
        destination = Path(self.build_lib)/'mcpywrap_core/skill'
        if destination.exists(): shutil.rmtree(destination)
        shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))

class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        shutil.copytree(skill_source(),Path(base_dir)/'mcpywrap_core/skill',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))

setup(cmdclass={'build_py':BuildPy,'sdist':Sdist})
