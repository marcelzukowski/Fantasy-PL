"""Generic OR-Tools installation check; contains no FPL solver implementation."""

import json
import sys

import ortools
from ortools.sat.python import cp_model


def main():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 3, "x")
    model.add(x <= 2)
    model.maximize(x)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 1
    status = solver.solve(model)
    assert status == cp_model.OPTIMAL
    assert solver.objective_value == solver.best_objective_bound == 2.0
    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "ortools": ortools.__version__,
                "status": solver.status_name(status),
                "objective": solver.objective_value,
                "bound": solver.best_objective_bound,
                "scope": "generic integer installation smoke; no FPL optimization",
            }
        )
    )


if __name__ == "__main__":
    main()
