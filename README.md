# Cinema TMS Admin 1.3.0 Beta 1

## GitHub 소스 관리

- 소스의 단일 원본은 비공개 GitHub 저장소 `https://github.com/Seikoz/Cinema-Tms-Admin`의 `main` 브랜치입니다.
- Git에는 `license_admin`, `automated_tests`, `deployment`, `docs`와 프로젝트 문서만 저장합니다.
- `data/licenses.db`, DB 백업, `.python`, `dist`, 개인키와 환경 파일은 `.gitignore`로 제외합니다. 특히 `data/licenses.db`는 암호화된 개인 발급키와 운영 계정을 포함하므로 GitHub에 업로드하지 않습니다.
- 다른 PC에서는 저장소를 Clone한 뒤 오프라인 런타임을 별도로 준비하고, 운영 DB는 프로그램을 완전히 종료한 상태에서 암호화된 별도 백업으로만 이전합니다.

```powershell
git clone https://github.com/Seikoz/Cinema-Tms-Admin.git Cinema_Tms_Admin
git pull --ff-only origin main
```

## 오프라인 프로그램 업데이트

- 관리자 계정으로 로그인한 뒤 `프로그램 업데이트` 버튼에서 `Cinema-TMS-Admin-Update-*.zip`을 선택합니다.
- `data\licenses.db`, 로그인 계정, 발급키와 감사 이력은 업데이트 대상에서 제외됩니다.
- 변경 전 프로그램 파일을 `data\update-backups`에 백업하고 실패 시 자동 복원합니다.
- `deployment\build-update-package.ps1`에 이전 파일 목록을 지정하면 변경된 부분만 포함하는 증분 업데이트를 만들 수 있습니다.

Cinema TMS의 오프라인 라이선스를 발급·갱신·관리하는 독립 관리자 프로젝트입니다.

TMS에서 저장한 장비 변경 요청 `.tmshw` 파일을 불러오면 이전 하드웨어 키의 활성 라이선스를 자동으로 찾아 고객·영화관·상영관 한도와 만료일을 채웁니다. 새 라이선스는 갱신 이력으로 연결되어 담당자와 처리 시각이 기록됩니다.

## 프로젝트 경계

- 관리자 소스, 실행기, 빌더, 테스트, 배포 ZIP은 이 프로젝트에서만 관리합니다.
- 암호화된 개인 발급키와 계정·발급 이력은 `data/licenses.db`에 저장합니다.
- `Cinema_Tms` 클라이언트 프로젝트에는 공개 검증키와 라이선스 검증 기능만 둡니다.
- 관리자 배포 ZIP에는 실제 `data/licenses.db`를 포함하지 않습니다.

## 클라우드 공유 DB

- 관리자 DB는 프로젝트의 `data\licenses.db`에 저장합니다.
- 최초 실행은 이 PC에서 진행해 관리자 계정과 암호를 정하고, DPAPI 보호 발급키를 DB 암호화 형식으로 이전합니다.
- 이후 프로젝트 폴더를 클라우드로 공유할 수 있지만, 관리자를 완전히 종료하고 동기화가 끝난 뒤 다른 PC에서 실행해야 합니다.
- 두 PC에서 동시에 실행하거나 클라우드 충돌본을 병합하지 마세요.

## 실행

`deployment\Cinema-TMS-Admin.vbs`를 실행합니다.

관리자 프로젝트는 자체 `.python` 오프라인 런타임만 사용하며 Cinema TMS 클라이언트 폴더를 참조하지 않습니다. 실행 중 처리되지 않은 Python 예외는 `data\admin-error.log`에 기록됩니다.

## 배포 패키지 생성

```powershell
powershell -ExecutionPolicy Bypass -File deployment\build-admin-package.ps1
```

## 중요

`data/licenses.db`와 관리자 계정 비밀번호를 모두 잃으면 개인 발급키를 복구할 수 없습니다. DB는 암호화된 별도 매체에도 백업하세요.
