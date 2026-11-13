' Silent background launcher for tg-system-control (no black window)
Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath
WshShell.Run "d:\VideoStudio_Mac\.venv\Scripts\pythonw.exe main.py", 0, False
