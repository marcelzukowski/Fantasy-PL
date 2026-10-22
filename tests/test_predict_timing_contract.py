import inspect

from fpl_engine.current import CurrentPredictionPipeline

def test_predict_current_emits_required_stage_timing_contract():
    source = inspect.getsource(CurrentPredictionPipeline.run)
    for key in ("input_load", "preparation", "simulation_total", "aggregation", "serialization", "total"):
        assert f'PREDICT_TIMING {key}=' in source
    assert 'fixtures={len(horizon)}' in source
    assert 'players={len(players)}' in source
    assert 'simulations_per_fixture={self.config.simulations_per_fixture}' in source
