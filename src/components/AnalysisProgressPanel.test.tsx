import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AnalysisProgressPanel } from "./AnalysisProgressPanel";
import type { AnalysisJob } from "../lib/types";

describe("AnalysisProgressPanel", () => {
  it("renders the current LLM analysis step with progress", () => {
    const job: AnalysisJob = {
      id: 7,
      project_id: 3,
      status: "running",
      current_step: "extract",
      progress: 42,
      message: "LLM이 인물, 장소, 조직, 아이템, 사건, 규칙, 떡밥을 추출 중입니다.",
      created_at: "2026-06-20 00:00:00",
      updated_at: "2026-06-20 00:00:01",
    };

    const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} />);

    expect(html).toContain("LLM 분석 진행 중");
    expect(html).toContain("엔티티 추출");
    expect(html).toContain("42%");
    expect(html).toContain('aria-valuenow="42"');
  });

  it("renders a failed analysis state", () => {
    const job: AnalysisJob = {
      id: 8,
      project_id: 3,
      status: "failed",
      current_step: "failed",
      progress: 100,
      message: "로컬 LLM 모델이 준비되지 않았습니다.",
      created_at: "2026-06-20 00:00:00",
      updated_at: "2026-06-20 00:00:01",
    };

    const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} />);

    expect(html).toContain("분석 실패");
    expect(html).toContain("로컬 LLM 모델이 준비되지 않았습니다.");
  });

  it("exposes cancellation while a long analysis is running", () => {
    const job: AnalysisJob = {
      id: 9, project_id: 3, status: "running", current_step: "gpt_index",
      progress: 12, message: "원고 검색 인덱스를 준비합니다 (12/100개 청크).",
      created_at: "", updated_at: "",
    };
    const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} onCancel={() => {}} />);
    expect(html).toContain("분석 중단");
  });

  it("shows an ETA based on completed non-cached windows", () => {
    const job = { id: 10, project_id: 3, status: "running", current_step: "gpt_wait", progress: 40,
      message: "GPT 응답 대기", created_at: "", updated_at: "",
      window_details: [
        { index: 1, chunk_id: 1, document: "1화", status: "completed", stage: "validated", attempts: 1, elapsed_seconds: 10, error: "" },
        { index: 2, chunk_id: 2, document: "2화", status: "completed", stage: "validated", attempts: 0, elapsed_seconds: 0, error: "", reused: true },
        { index: 3, chunk_id: 3, document: "3화", status: "queued", stage: "queued", attempts: 0, elapsed_seconds: 0, error: "" },
      ],
    } as AnalysisJob;
    const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} />);
    expect(html).toContain("현재 처리 속도 기준 약 10초 남음");
  });
});

it('shows partial completion with actionable persisted failure details', () => {
  const job = { id: 1, project_id: 1, status: 'partial', current_step: 'gpt_partial',
    progress: 90, message: '기존 결과 유지', created_at: '', updated_at: '',
    window_details: [{ index: 7, chunk_id: 80, document: '7화 · 봉인', status: 'failed',
      stage: 'request', attempts: 3, elapsed_seconds: 137, error: 'GPT 응답 시간 초과', error_code: 'provider_unavailable' }],
  } as AnalysisJob;
  const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} onRetry={() => {}} />);
  expect(html).toContain('일부 구간 재시도 필요');
  expect(html).toContain('7화 · 봉인');
  expect(html).toContain('GPT 응답 시간 초과');
  expect(html).toContain('시도 3회');
  expect(html).toContain('오류 코드: provider_unavailable');
  expect(html).toContain('남은 구간 이어서 분석');
  expect(html).not.toContain('그래프 저장');
});

it('shows failed split parts and retained sibling successes', () => {
  const job = { id: 2, project_id: 1, status: 'partial', current_step: 'gpt_partial',
    progress: 50, message: '기존 결과 유지', created_at: '', updated_at: '',
    window_details: [{ index: 1, chunk_id: 1, document: '1화', status: 'failed',
      stage: 'wait', attempts: 3, elapsed_seconds: 80, error: '응답 시간 초과',
      parts: [{ path: 'L', chunk_ids: [1, 2, 3], status: 'failed', error: '응답 시간 초과' },
              { path: 'R', chunk_ids: [4, 5, 6], status: 'completed', error: '', reused: true }] }],
  } as AnalysisJob;
  const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} onRetry={() => {}} />);
  expect(html).toContain('세부 구간 앞부분');
  expect(html).toContain('실패');
  expect(html).toContain('세부 구간 뒷부분');
  expect(html).toContain('저장 결과 재사용');
});

it('explains remaining chapters were not requested after an account failure', () => {
  const job = { id: 3, project_id: 1, status: 'failed', current_step: 'failed',
    progress: 100, message: 'GPT 계정 사용 한도에 도달했습니다.', created_at: '', updated_at: '',
    window_details: [
      { index: 3, chunk_id: 3, document: '3화', status: 'failed', stage: 'wait', attempts: 1, elapsed_seconds: 2, error: '사용 한도' },
      { index: 4, chunk_id: 4, document: '4화', status: 'deferred', stage: 'deferred', attempts: 0, elapsed_seconds: 0, error: '' },
    ],
  } as AnalysisJob;
  const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} onRetry={() => {}} />);
  expect(html).toContain('아직 요청하지 않은 구간 1개');
  expect(html).toContain('저장된 성공 구간은 다시 요청하지 않습니다');
});

it('bounds a long failure list and exposes filters and pagination', () => {
  const job = { id: 4, project_id: 1, status: 'partial', current_step: 'gpt_partial', progress: 50,
    message: '기존 결과 유지', created_at: '', updated_at: '', window_details: Array.from({length:120},(_,i)=>({
      index:i+1,chunk_id:i+1,document:`원고 ${i+1}화`,status:'failed',stage:'wait',attempts:1,elapsed_seconds:45,error:'시간 초과',
    })), } as AnalysisJob;
  const html=renderToStaticMarkup(<AnalysisProgressPanel job={job}/>);
  expect((html.match(/번째 구간/g)??[]).length).toBe(8);
  expect(html).toContain('분석 기록 다음 페이지');
  expect(html).toContain('검증 완료');
  expect(html).toContain('원고 8화');
  expect(html).not.toContain('원고 9화');
});

it('explains interrupted windows and saved retry settings without calling them running', () => {
  const job = { id: 5, project_id: 1, status: 'failed', current_step: 'failed', progress: 42,
    message: '앱이 종료되어 분석이 중단되었습니다.', created_at: '', updated_at: '',
    review_context: {model:'luna',effort:'medium'},
    window_details: [
      {index:1,chunk_id:1,document:'1화 · 성공',status:'completed',stage:'validated',attempts:1,elapsed_seconds:10,error:''},
      {index:2,chunk_id:2,document:'2화 · 중단 위치',status:'interrupted',stage:'wait',attempts:2,elapsed_seconds:24,error:'응답을 기다리던 중 앱이 종료되었습니다.',
        parts:[{path:'L',chunk_ids:[2],status:'completed',error:'',reused:true}, {path:'R',chunk_ids:[3],status:'interrupted',error:'앱 종료'}]},
      {index:3,chunk_id:4,document:'3화 · 미실행',status:'deferred',stage:'queued',attempts:0,elapsed_seconds:0,error:''},
    ],
  } as AnalysisJob;
  const html=renderToStaticMarkup(<AnalysisProgressPanel job={job} onRetry={()=>{}}/>);
  expect(html).toContain('2화 · 중단 위치');
  expect(html).toContain('중단');
  expect(html).toContain('검증 완료 1');
  expect(html).toContain('미실행 1');
  expect(html).toContain('남은 구간 이어서 분석');
  expect(html).toContain('luna');
  expect(html).toContain('Medium');
  expect(html).not.toContain('처리 중');
});

it('renders legacy unfinished records as stopped when their job already ended', () => {
  const job = { id:6,project_id:1,status:'cancelled',current_step:'cancelled',progress:100,
    message:'이전 버전에서 중단',created_at:'',updated_at:'',window_details:[
      {index:1,chunk_id:1,document:'구형 중단 구간',status:'running',stage:'wait',attempts:1,elapsed_seconds:9,error:''},
      {index:2,chunk_id:2,document:'구형 미실행',status:'queued',stage:'queued',attempts:0,elapsed_seconds:0,error:''},
    ] } as AnalysisJob;
  const html=renderToStaticMarkup(<AnalysisProgressPanel job={job}/>);
  expect(html).toContain('구형 중단 구간');
  expect(html).toContain('미실행 1');
  expect(html).not.toContain('처리 중');
  expect(html).not.toContain('100%');
});

it('shows verified records by default after a successful retry', () => {
  const job={id:7,project_id:1,status:'completed',current_step:'completed',progress:100,message:'완료',created_at:'',updated_at:'',
    window_details:[{index:1,chunk_id:1,document:'재사용한 회차',status:'completed',stage:'validated',attempts:0,elapsed_seconds:0,error:'',reused:true}]} as AnalysisJob;
  const html=renderToStaticMarkup(<AnalysisProgressPanel job={job}/>);
  expect(html).toContain('재사용한 회차');
  expect(html).toContain('저장 결과 재사용');
  expect(html).not.toContain('선택한 상태의 구간이 없습니다');
});
