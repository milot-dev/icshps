from pathlib import Path
from icshps.graph import run_initial_workflow

result = run_initial_workflow(
    Path("data/hiring_bundles/clean_standard_application"),
    runs_root=Path("runs"),
)

print(result.status)
print(result.ready_for_downstream)
print(result.run_dir)