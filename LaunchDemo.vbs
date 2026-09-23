' Double-click on Windows after installing requirements into .venv.
Option Explicit
Dim fs, sh, root, pythonw, launcher
Set fs = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
pythonw = fs.BuildPath(root, ".venv\Scripts\pythonw.exe")
launcher = fs.BuildPath(root, "launch_demo.pyw")
If Not fs.FileExists(pythonw) Then
    MsgBox "Python environment not found. Follow the README installation steps first.", vbCritical, "Money Graph"
    WScript.Quit 1
End If
sh.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & launcher & Chr(34), 0, False
