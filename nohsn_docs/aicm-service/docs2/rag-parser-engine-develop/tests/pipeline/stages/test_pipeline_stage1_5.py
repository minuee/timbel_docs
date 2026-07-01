from src.pipeline.stages.pipeline import LLMPipeline


def test_pipeline_instantiates_layout_mapper():
    p = LLMPipeline()
    assert hasattr(p, "_stage1_5")
    from src.pipeline.stages.stage1_5_layout import LayoutMapper
    assert isinstance(p._stage1_5, LayoutMapper)
