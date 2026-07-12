import subprocess
from pathlib import Path


def test_portfolio_core_node_suite():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", "tests/portfolio-core.test.js"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
