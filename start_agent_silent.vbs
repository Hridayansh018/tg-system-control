' Silent background launcher for tg-system-control (no console window)
' Python selection: project .venv, then pythonw on PATH (if it has the packages),
' then the legacy VideoStudio venv, then plain pythonw.
Set WshShell = CreateObject("WScript.Shell")
Set Fso = CreateObject("Scripting.FileSystemObject")
strPath = Fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath

pyw = ""
If Fso.FileExists(strPath & "\.venv\Scripts\pythonw.exe") Then
    pyw = strPath & "\.venv\Scripts\pythonw.exe"
ElseIf WshShell.Run("cmd /c python -c ""import requests, PIL""", 0, True) = 0 Then
    pyw = "pythonw"
ElseIf Fso.FileExists("D:\VideoStudio_Mac\.venv\Scripts\pythonw.exe") Then
    pyw = "D:\VideoStudio_Mac\.venv\Scripts\pythonw.exe"
Else
    pyw = "pythonw"
End If

WshShell.Run """" & pyw & """ """ & strPath & "\main.py""", 0, False
