# kknaks-mobile 문서 위키

프로젝트 내 모든 문서의 진입점. 카테고리별로 정리하고, 각 문서는 짧은 한 줄 설명과 상태·최종 업데이트를 함께 표기한다.

## 문서 작성 규칙

- 파일명: `NNN-kebab-case.md` (카테고리 내에서 순번 독립 증가)
- 모든 문서 상단에 프론트매터 필수:

```yaml
---
title: 문서 제목
type: spec | plan | refactor | adr | troubleshooting
status: draft | active | done | archived
created: YYYY-MM-DD
updated: YYYY-MM-DD
related: []    # 관련 문서 경로 (예: spec/001-xxx.md)
---
```

- 문서가 추가/상태 변경되면 이 위키(아래 인덱스)도 같이 갱신한다.

## 카테고리

| 디렉토리 | 용도 |
|---|---|
| [`spec/`](spec/) | 기능·요구사항 명세. "무엇을 만들 것인가" |
| [`plan/`](plan/) | 구현 계획, 작업 분해, 로드맵. "어떻게·언제 만들 것인가" |
| [`refactor/`](refactor/) | 리팩토링 제안 및 기록. "왜 바꿨고 무엇이 바뀌었는가" |
| [`adr/`](adr/) | 아키텍처 결정 기록 (Architecture Decision Record) |
| [`troubleshooting/`](troubleshooting/) | 이슈 진단/해결 로그 |

## 인덱스

### Spec

_(문서 없음)_

### Plan

_(문서 없음)_

### Refactor

_(문서 없음)_

### ADR

_(문서 없음)_

### Troubleshooting

_(문서 없음)_
