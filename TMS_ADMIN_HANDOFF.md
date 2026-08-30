# Cinema TMS Admin — 작업 인수인계

최종 갱신: 2026-08-30
기준 소스: **v1.3.0 Beta 3**
실제 작업 경로: `D:\Codex\Cinema_Tms_Admin`

## GitHub 기준 소스

- 단일 원본 저장소: `https://github.com/Seikoz/Cinema-Tms-Admin`
- 기준 브랜치: `main`
- 작업 전 `git pull --ff-only origin main`, 작업 완료 후 테스트·커밋·`git push origin main` 순서로 동기화합니다.
- `AGENTS.md`가 Codex 작업 시작 시 `status → fetch → 원격 커밋 확인 → 깨끗할 때만 ff-only pull`, 완료 시 `테스트 → 민감 파일 제외 확인 → commit → push` 절차를 강제합니다.
- 새 PC에서는 기존 폴더를 덮어쓰지 말고 저장소를 `Cinema_Tms_Admin`으로 Clone합니다.
- `data`, `.python`, `.venv`, `dist`, DB, 개인키, 환경 파일은 Git에서 제외합니다. 특히 `data\licenses.db`와 백업 DB는 GitHub로 이동하지 않고 프로그램 종료 후 암호화된 별도 백업으로 이전합니다.

```powershell
git clone https://github.com/Seikoz/Cinema-Tms-Admin.git Cinema_Tms_Admin
git pull --ff-only origin main
```

작업 트리에 미커밋 변경이 있거나 로컬·원격 이력이 갈라졌으면 자동 병합하거나 강제로 덮어쓰지 않습니다. `git push --force`와 `git reset --hard`는 사용하지 않으며 변경을 보존한 상태로 먼저 충돌 내용을 확인합니다.

## 역할

- Cinema TMS 클라이언트 하드웨어 키(`.tmshw`) 검증
- Ed25519 오프라인 라이선스 발급·갱신
- 관리자·발급 담당자·조회 전용 로그인 계정 관리
- 발급 이력과 감사 로그 관리

## 중요 데이터

- `data\licenses.db`: 암호화된 개인키, 관리자 계정, 발급 이력 및 감사 로그
- 이 DB는 클라이언트 TMS 배포본과 관리자 배포 ZIP에 포함하지 않습니다.
- 프로젝트 폴더를 클라우드로 공유할 수 있지만 한 번에 한 PC에서만 실행합니다. 프로그램 종료와 동기화 완료 후 다른 PC에서 엽니다.
- 최초 실행은 발급키를 만든 현재 PC에서 관리자 계정 설정을 완료해야 하며, 이후 암호화된 DB는 다른 PC에서도 같은 관리자 암호로 사용할 수 있습니다.

## 배포

- 빌더: `deployment\build-admin-package.ps1`
- 현재 패키지: `dist\Cinema-TMS-Admin-1.3.0b3-Windows-x64.zip`
- 관리자 배포 ZIP에는 `data\licenses.db`를 포함하지 않습니다.

## 프로그램 업데이트

- 관리자 계정만 상단 `프로그램 업데이트` 버튼을 사용할 수 있습니다.
- 업데이트 패키지 빌더는 `deployment\build-update-package.ps1`, 적용기는 `deployment\apply-update.ps1`입니다.
- 기준 파일 목록 없이 만들면 전체 프로그램 업데이트, `-BaselineManifestPath`를 지정하면 변경 파일만 포함하는 증분 업데이트가 생성됩니다.
- 업데이트 대상은 `license_admin`, `deployment`, `docs`와 프로그램 루트 문서로 제한됩니다.
- `data`, `.python`, `.venv`, `dist`는 업데이트 대상이 아니므로 `licenses.db`, 로그인 계정, 암호화된 발급키, 발급·감사 이력이 유지됩니다.
- 적용 전 프로그램 파일을 `data\update-backups`에 백업하고 실패하면 자동 롤백합니다.
- 업데이트 ZIP의 제품 ID, 경로, 크기, SHA-256을 검증하고 완료 후 관리자 프로그램을 다시 실행합니다.
- 이 기능은 하위 호환되는 새 운영 기능이므로 `1.1.0b3`에서 `1.2.0b1`로 마이너 판올림했습니다.

## 장비 변경 재귀속

- TMS의 `장비 변경 요청 파일 저장`으로 생성한 `.tmshw`를 불러오면 이전 키와 일치하는 활성 발급 이력을 자동으로 찾습니다.
- 고객, 영화관, 상영관 한도와 만료일을 채우고 새 하드웨어 키로 갱신 발급합니다.
- 새 발급 이력은 이전 라이선스를 `supersedes`로 연결하며 처리 담당자와 처리 시각을 그대로 감사 기록에 남깁니다.
- 이전 활성 발급 이력이 관리자 DB에 없으면 자동 연결을 중단하고 명확한 오류를 표시합니다.

## 클라이언트 호환 규격

- `license_admin\contract.py`의 제품 ID, 스키마와 공개 검증키는 `Cinema_Tms\app\licensing.py`와 일치해야 합니다.
- 자동 테스트가 두 프로젝트가 같은 공개 규격을 사용하는지 확인합니다.

## VBS 한글 입력 호환성

- `deployment\Cinema-TMS-Admin.vbs`는 GUI 서브시스템의 `pythonw.exe`를 `SW_SHOWNORMAL` 상태로 실행한다. 이전의 숨김 `python.exe` 실행은 Windows 한글 IME 포커스·조합 문맥을 불안정하게 만들 수 있어 제거했다.
- `license_admin\manager.pyw`는 Windows에서 Tk 기본 글꼴을 `Malgun Gothic`으로 지정하며 문자열 조합은 Windows IME와 Tk 기본 입력 처리에 맡긴다.
- 입력창에 별도 KeyPress·검증 콜백을 연결하지 않아 조합 중인 한글을 강제로 읽거나 변경하지 않는다.
- Windows 입력 호환성 수정이므로 `PATCH`로 분류해 `1.3.0b2`로 올렸다.

### Beta 3 추가 수정

- VBS 실행 방식 변경만으로 해결되지 않은 Windows 한글 IME 조합 문제를 위해 편집 가능한 `ttk.Entry`를 `KoreanImeEntry(tk.Entry)`로 교체했다.
- 고객명·영화관명·날짜와 `FormDialog` 기반 로그인/계정 입력창에 적용하며 읽기 전용 하드웨어 키 필드는 기존 ttk 위젯을 유지한다.
- 별도의 `KeyPress`, `KeyRelease`, `validatecommand`를 연결하지 않아 조합 중 문자열을 Python 코드가 변경하지 않는다.
- 같은 호환성 오류의 추가 수정이므로 `PATCH`로 분류해 `1.3.0b3`로 올렸다.
# 1.3.0 Beta 4 인수인계

- Windows에서 편집 가능한 입력창은 `license_admin/windows_ime.py`의 네이티브 `EDIT` 컨트롤을 사용합니다.
- 목적은 한글 조합 글자가 Tk 보조 창에 따로 표시되는 현상을 없애고 Windows IME의 인라인 조합을 사용하는 것입니다.
- `WindowsImeEntry`는 기존 `StringVar`와 양방향 동기화되며, 로그인·계정 관리 모달에서도 같은 컨트롤을 사용합니다.
- 네이티브 입력 컨트롤 변경은 DB 스키마, 발급키 및 라이선스 파일 형식에 영향을 주지 않습니다.
# 1.3.0 Beta 5 인수인계

- `1.3.0b4`의 ctypes Win32 창 프로시저 콜백은 Windows 종료 코드 `0xC0000409`를 일으켜 제거했습니다.
- `WindowsImeEntry`는 네이티브 `EDIT` 컨트롤을 유지하되, 입력값을 Tk `after(30, ...)` 이벤트 루프에서 동기화합니다.
- 향후에도 Python ctypes 콜백으로 네이티브 입력창의 `WNDPROC`를 교체하지 마세요.
