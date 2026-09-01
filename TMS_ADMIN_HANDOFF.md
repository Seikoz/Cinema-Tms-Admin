# Cinema TMS Admin — 작업 인수인계

최종 갱신: 2026-09-02
기준 소스: **v1.6.0 Beta 3**
실제 작업 경로: `D:\Codex\Cinema_Tms_Admin`

## 1.6.0 Beta 3 자동 업데이트 자격 증명 DB 이전

- 공용 읽기 전용 PAT는 `licenses.db.secure_settings`에 AES-GCM 암호문으로 저장한다.
- AES 키는 로그인으로 해제된 Ed25519 발급키에서 HKDF-SHA256의 업데이트 전용 컨텍스트로 파생한다. DB만 보유하거나 소스만 보유해서는 토큰을 복호화할 수 없다.
- 기존 `data/github-update-token.dpapi`가 있으면 관리자 로그인 직후 DB 저장과 재복호화 검증을 마친 뒤 파일을 제거한다.
- VBS에서 실행한 라이선스 관리자 온라인 업데이트와 라이선스 발급은 DB 토큰을 자동 사용한다. GitHub 로그인 및 토큰 입력 UI는 없다.
- TMS에는 토큰 원문이 아니라 `.tmshw` 공개키에 맞춰 재암호화한 `update_credential`만 서명 라이선스에 포함한다.
- 보안 저장 흐름 보완이므로 PATCH로 분류해 `1.6.0b3`으로 올렸다.

## 1.6.0 Beta 2 로컬 GitHub 게시 인수인계

- `UPDATE_RELEASE_TOKEN`과 `.github/workflows/publish-update.yml`을 제거했다.
- 개발 PC에서 `gh auth login` 후 `deployment\publish-github-update.ps1`을 실행해 테스트부터 `admin-v<버전>` 중앙 Release 게시까지 수행한다.
- GitHub CLI 로그인 정보는 개발 PC 자격 증명 저장소에만 두며 소스·배포본·관리자 DB에 복사하지 않는다.

## 1.6.0 Beta 1 공용 업데이트 토큰 인수인계

- 공용 읽기 전용 PAT는 관리자 DB에 로그인 발급키 기반 암호문으로 저장하며 소스·설치본에는 포함하지 않는다.
- `.tmshw` 스키마 2의 X25519 공개키를 사용해 토큰을 장비별로 암호화하고, 라이선스 스키마 4의 서명 payload에 넣는다.
- `licenses.db`에는 발급 당시 공개키만 저장한다. 기존 요청 스키마 1은 이력 조회 호환만 하며 자동 토큰 발급에는 최신 `.tmshw`가 필요하다.
- 토큰 교체·폐기 후에는 관리자에서 새 토큰을 설정하고 대상 장비 라이선스를 재발급해야 한다.

## 1.5.0 Beta 2 업데이트 저장소 분리

- 관리자 프로그램은 `Seikoz/Cinema-Tms-Updates`에서 `admin-v<버전>` Release만 조회한다.
- 이 버전에서 도입했던 `UPDATE_RELEASE_TOKEN` 방식은 1.6.0 Beta 2에서 폐기했으며 다시 설정하지 않는다.
- 두 토큰은 용도와 권한을 분리하고 소스·배포본·DB에 포함하지 않는다.
- `.github/workflows/publish-update.yml`은 `v<버전>` 소스 태그를 중앙 저장소의 `admin-v<버전>` Release로 변환해 게시한다.
- 권한과 배포 경로를 분리한 호환 수정이므로 `PATCH`인 `1.5.0b2`로 올렸다.

## 1.5.0 Beta 1 비공개 GitHub 온라인 업데이트

- 관리자 계정만 `온라인 업데이트`를 사용할 수 있으며 토큰 입력 UI는 제공하지 않는다.
- `license_admin/github_updates.py`가 `Seikoz/Cinema-Tms-Admin` 비공개 Release의 업데이트 ZIP과 SHA-256을 인증 다운로드하고 검증한다.
- Fine-grained PAT는 해당 저장소의 Contents 읽기 권한만 부여하며 `licenses.db`에는 로그인 발급키 기반 AES-GCM 암호문만 저장한다.
- `.github/workflows/publish-update.yml`은 앱 버전과 일치하는 `v*` 태그에서 Release와 자산을 생성한다.
- 실제 온라인 업데이트 기능 추가이므로 `MINOR`로 분류해 `1.5.0b1`로 올렸다.

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

- 관리자 계정만 상단 `파일 업데이트` 버튼을 사용할 수 있습니다.
- `온라인 업데이트`는 관리자 계정에서만 활성화되며 비공개 GitHub Release를 사용합니다.
- 저장소 읽기 전용 토큰은 관리자 DB 암호문에서 로그인 후 자동으로 사용합니다.
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
# 1.3.0 Beta 6 인수인계

- `deployment/Cinema-TMS-Admin.vbs`는 Windows Script Host의 한글 호환성을 위해 UTF-16 LE BOM으로 유지해야 합니다.
- VBS를 수정한 뒤 UTF-8로 저장하면 오류 메시지가 다시 깨질 수 있으므로 테스트에서 BOM을 확인합니다.
- `1.3.0b5`의 네이티브 입력창 안정화 수정이 포함되어 있습니다.
# 1.3.0 Beta 7 인수인계

- `WindowsImeEntry`의 Tab/Shift+Tab 포커스 이동은 `GetAsyncKeyState`를 Tk 이벤트 루프에서 확인해 처리합니다.
- 한 번의 Tab이 여러 네이티브 입력창에서 중복 처리되지 않도록 클래스 공유 `_tab_key_consumed` 상태를 유지합니다.
- `WNDPROC` 교체나 ctypes 콜백 방식으로 되돌리지 마세요.
# 1.4.0 Beta 1 인수인계

- 일반 `.tmshw`를 불러올 때 `LicenseAuthority.latest_license_for_hardware_key()`로 동일 하드웨어 키의 최신 발급 이력을 조회합니다.
- 기존 정보가 있으면 고객명, 영화관명, 상영관 한도를 채우고 이전 기간·상태·담당자를 표시합니다.
- 최신 이력이 `active`인 경우에만 `rebind_supersedes`에 라이선스 ID를 넣어 갱신으로 연결합니다.
- `revoked` 등 비활성 이력은 참고 정보만 불러오고 신규 발급으로 처리합니다.
# 1.4.0 Beta 2 인수인계

- 기존 만료일을 연장할 때 `license_admin.core.extended_license_expiry()`를 사용해 `date.max` 범위를 넘지 않도록 합니다.
- `9999-12-31` 라이선스는 갱신 입력값에서도 그대로 유지합니다.
- 하드웨어 키 자동 조회 로직에서 직접 `timedelta(days=365)`를 더하지 마세요.
# 1.4.0 Beta 3 인수인계

- 발급 이력 Treeview에는 `hardware` 열과 가로·세로 스크롤이 있으며 ID 열은 축소되지 않는 최소 너비를 사용합니다.
- `WindowsImeEntry`의 네이티브 HFONT는 Tk `TkTextFont`의 실제 family, size, weight, slant에서 계산합니다.
- DB에는 시간을 UTC로 계속 저장하고 GUI 표시는 `local_datetime()`에서 고정 UTC+9로 변환합니다.
