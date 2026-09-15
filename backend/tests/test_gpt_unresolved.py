"""Unresolved model references are diagnostics, not failed review windows."""
import json
from types import SimpleNamespace

from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer, parse_review_result
from backend.app.pipeline.gpt_graph import GroundedGraph
from backend.tests.test_gpt_analysis import fixture, graph_payload


def test_missing_endpoint_publishes_valid_graph_and_grounded_diagnostic(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    payload = graph_payload(ids)
    payload['relations'].append({**payload['relations'][0], 'target': 'missing'})
    analyzer = GptStoryAnalyzer(repo, rag, SimpleNamespace(
        complete=lambda *a, **k: {'text': json.dumps(payload)}))
    result = analyzer.analyze(project.id, 'model', 'low')
    assert result['published'] is True
    assert result['failed_window_count'] == 0
    graph = repo.graph(project.id)
    assert len(graph.relations) == 2
    unresolved = [entity for entity in graph.entities if entity.is_unresolved]
    assert len(unresolved) == 1
    assert '원고의 설정 오류로 확정한 것이 아닙니다' in unresolved[0].summary
    edge = next(edge for edge in graph.relations if edge.has_unresolved_endpoint)
    assert edge.target_entity_id == unresolved[0].id
    assert edge.evidence_chunk_ids == [ids[1]]
    assert edge.claims[0].quotes[0].quote == '유나는 계약 없이 검을 쓴다.'
    assert '분석 확인 필요' in edge.claims[0].explanation
    assert edge.claims[0].basis == 'inferred'
    assert graph.health.dangling_relation_count == 1
    assert repo.list_documents(project.id)[0].analysis_status == 'analyzed'
    assert not graph.issues  # Do not turn an extraction defect into a story verdict.

    seeded = analyzer._seed_graph_outside_range(project.id, set())
    assert any(value.get('is_unresolved') for value in seeded.entities.values())
    assert all('미확인 대상' not in row['target'] for row in seeded.prompt_context())
    analyzer.analyze(project.id, 'model', 'low')
    rerun = repo.graph(project.id)
    assert [entity.id for entity in rerun.entities if entity.is_unresolved] == [unresolved[0].id]
    assert rerun.health.dangling_relation_count == 1


def test_endpoint_name_is_resolved_only_when_unambiguous(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    payload = graph_payload(ids)
    payload['relations'][0]['source'] = '유나'
    payload['relations'][0]['target'] = '검'
    result = GptStoryAnalyzer(repo, rag, SimpleNamespace(
        complete=lambda *a, **k: {'text': json.dumps(payload)})).analyze(project.id, 'model', 'low')
    assert result['published']
    graph = repo.graph(project.id)
    assert len(graph.relations) == 1
    assert not any(entity.is_unresolved for entity in graph.entities)


def test_reused_unknown_model_ids_do_not_merge_different_windows():
    graph = GroundedGraph()
    for ids in ([1, 2], [3, 4]):
        payload = graph_payload(ids)
        payload['relations'][0].update(source='absent_source', target='absent_target')
        result = parse_review_result(json.dumps(payload))
        context = {ids[0]: {'text': '계약자만 검을 쓴다.'},
                   ids[1]: {'text': '유나는 계약 없이 검을 쓴다.'}}
        graph.add(result.entities, result.relations, context, ids[1])
    assert len(graph.relations) == 2
    assert sum(entity.get('is_unresolved', False) for entity in graph.entities.values()) == 4
    assert graph.prompt_context() == []


def test_ambiguous_name_is_not_arbitrarily_connected():
    payload = graph_payload([1, 2])
    payload['entities'].append({**payload['entities'][1], 'id': 's2', 'type': 'rule'})
    payload['relations'][0]['target'] = '검'
    result = parse_review_result(json.dumps(payload))
    graph = GroundedGraph()
    graph.add(result.entities, result.relations,
              {1: {'text': '계약자만 검을 쓴다.'}, 2: {'text': '유나는 계약 없이 검을 쓴다.'}}, 2)
    assert sum(entity.get('is_unresolved', False) for entity in graph.entities.values()) == 1
