Option Explicit

Dim fso, shell, deploymentFolder, projectFolder, pythonPath, scriptPath, command, exitCode
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
deploymentFolder = fso.GetParentFolderName(WScript.ScriptFullName)
projectFolder = fso.GetParentFolderName(deploymentFolder)
pythonPath = projectFolder & "\.python\python.exe"
If Not fso.FileExists(pythonPath) Then pythonPath = projectFolder & "\.venv\Scripts\python.exe"
scriptPath = projectFolder & "\license_admin\manager.pyw"
If Not fso.FileExists(pythonPath) Then
    MsgBox "Cinema TMS Admin 전용 Python 실행 파일을 찾을 수 없습니다." & vbCrLf & pythonPath & vbCrLf & "최신 관리자 ZIP을 완전히 압축 해제하세요.", vbCritical, "Cinema TMS License Manager"
    WScript.Quit 2
End If
If Not fso.FileExists(scriptPath) Then
    MsgBox "라이선스 관리 프로그램을 찾을 수 없습니다." & vbCrLf & scriptPath, vbCritical, "Cinema TMS License Manager"
    WScript.Quit 3
End If
shell.CurrentDirectory = projectFolder
command = Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & scriptPath & Chr(34)
exitCode = shell.Run(command, 0, True)
If exitCode <> 0 Then MsgBox "라이선스 관리 프로그램 실행에 실패했습니다. 종료 코드: " & exitCode, vbCritical, "Cinema TMS License Manager"
