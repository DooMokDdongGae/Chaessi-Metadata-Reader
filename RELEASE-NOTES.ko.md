# 채씨 메타데이터 리더 1.1.0

Windows x64 · 2026-11-26 · 빌드 `reader-20261126-01-public` · 순번 `2026112601`

[공식 1.1.0 릴리스](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.1.0) · [최신 안정판](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/latest) · [설치·사용 안내](README.ko.md) · [AI 설치 도우미 지시문](README.ko.md#ai-setup)

- **공식 서명 패키지 검증.** PUBLIC 생산 신뢰로 발행자 키·서명·유효 기간·폐기·최고 순번과 전체 리소스·실제 수신 프로세스·소켓을 확인합니다. 시험 키와 임의 무서명 PRIVATE 빌드는 승인하지 않습니다. 서명 Portable은 EXE와 동봉 서명·키 파일 4개를 함께 보관하세요. 새 Preset 공개판이 이미 발행되었다는 안내는 아닙니다.
- **기존 공식 3.8.5 유지.** 2026-11-23 수정본의 공식 CHAESSI PRESET 3.8.5 Portable 및 `chaessi.prompt-transfer/1`, 요청별 nonce/HMAC 인증은 유지합니다. 받을 Base/Character Positive/Undesired를 정하고 프리셋에서 미리보기·취소·적용·Undo를 사용합니다. 전송은 저장·History·이미지 생성을 실행하지 않습니다.
- **Setup 하나.** `Chaessi-Metadata-Reader-Setup-x64.exe`는 `D:\MApp\Chaessi Reader` 신규 설치와 허용된 정확한 공식 1.0.x/D 이전판 `2026112502` 업데이트용입니다. 임의 폴더·혼합·변조·알 수 없는 빌드는 거부합니다. 정상 종료 후 실행하세요. 설정·페어링·등록 및 기존 Chrome 확장 **0.3.1**은 유지합니다. 확장을 처음 설치할 때만 ZIP을 고정 폴더에 풀고 사용자가 Chrome에서 로드·최초 권한을 확인하세요.
- **복구와 구판 주의.** 중단된 작업은 같은 Setup을 재실행해 복구 안내를 따르세요. 충돌 시 파일과 기록을 보존하세요. 보호 없는 예전 설치기를 나중에 실행하는 것까지 막을 수 없으므로 구 Setup으로 덮어쓰지 마세요. Windows 설치기는 코드 서명이 없으므로 파일명과 SHA-256을 대조하고 정책을 우회하지 마세요.

## 알려진 제한과 검증 범위

기존 격리 서명 후보에서 미리보기 전송 약 **6.97초**, 전체 인증 약 **14.35초**가 관찰됐습니다. 이번 공개판의 보장 시간이 아니며 환경에 따라 대기가 길 수 있습니다. 처음 실행한 Preset의 발견이 실패하면 화면 준비 후 연결을 다시 시도하세요. 기존 설치·D 업데이트·롤백·제거·UI·전송·오프라인 PNG 검증을 재사용했으며, 최신 후보에서 온라인 Chrome/NovelAI Inspect 수집 전체를 재시험하지 않았습니다. 오프라인 미수신 폐기 정보, 로컬 시계와 같은 사용자 저장소 훼손은 운영 한계입니다.

[기존 1.0.1](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.1) · [1.0.0 빌드 2026112401](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0%2B2026112401) · [1.0.0 기준판](https://github.com/DooMokDdongGae/Chaessi-Metadata-Reader/releases/tag/v1.0.0)
