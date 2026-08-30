# Cinema TMS Admin 1.3.0 Beta 6

## VBS 한글 오류 메시지 수정

- Windows Script Host가 VBS의 UTF-8 한글을 시스템 ANSI 문자로 잘못 해석해 오류 문구가 깨지던 문제를 수정했습니다.
- `Cinema-TMS-Admin.vbs`를 Windows Script Host가 안정적으로 인식하는 UTF-16 LE BOM 형식으로 배포합니다.
- `1.3.0b5`의 네이티브 입력창 강제 종료 수정도 그대로 포함합니다.

Windows 실행기 호환성 수정이므로 `PATCH`로 판단해 `1.3.0b6`로 올렸습니다.
