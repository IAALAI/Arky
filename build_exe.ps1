$ErrorActionPreference = "Stop"
pyinstaller main.spec
Copy-Item -Path "conf", "data", "res", "aria2c.exe" -Destination "dist\main" -Recurse
