@echo off
pushd "%~dp0.."
set "TMS_PYTHON=.python\pythonw.exe"
if not exist "%TMS_PYTHON%" set "TMS_PYTHON=.venv\Scripts\pythonw.exe"
if not exist "%TMS_PYTHON%" (
  echo Cinema TMS Admin 전용 Python 실행 파일을 찾을 수 없습니다.
  echo 최신 관리자 ZIP을 완전히 압축 해제하세요.
  pause
  popd
  exit /b 2
)
start "" "%TMS_PYTHON%" "license_admin\manager.pyw"
popd
