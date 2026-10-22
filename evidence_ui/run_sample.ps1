$ErrorActionPreference = 'Stop'
$componentRoot = $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$componentRoot\src;$componentRoot\.deps;$previousPythonPath"
    py -3.12 -m streamlit run "$componentRoot\app.py" --global.developmentMode false --browser.gatherUsageStats false --server.address 127.0.0.1 --server.maxUploadSize 20 --server.fileWatcherType none
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
