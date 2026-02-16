from pathlib import Path

import pytest

from nuberu.core.simulation_builder import SimulationBuilder


def test_simulation_from_yaml_minimal():
    cfg_file = Path(__file__).parent / "config_poisson_drain_simple_q0.yaml"
    sim = SimulationBuilder(cfg_file)
    assert sim.cfg.stop_time == pytest.approx(0.1)
    # Build and run to smoke-test
    # Without these steps, the load of the pickles is not done, so an error in
    # the config file would not be caught.
    s = sim.build()
    s.run()
