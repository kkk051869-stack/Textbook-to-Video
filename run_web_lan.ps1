Set-Location -LiteralPath 'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
& 'D:\anaconda3\envs\textbook2video\python.exe' 'D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\run_web_lan.py' *> 'output\web_demo\lan_web.log'
