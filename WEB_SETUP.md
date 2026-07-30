# Web 演示界面

这个界面用于本地演示 Textbook-to-Video 的核心流程：上传教材、选择课节、启动生成、查看日志并下载 MP4。

## 启动

```powershell
.venv\Scripts\python.exe web_app.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

## 依赖

```powershell
.venv\Scripts\pip.exe install -r requirements-web.txt
```

## 使用流程

1. 上传 DOCX 或 PDF 教材。
2. 等待系统读取课节列表。
3. 选择课节、视觉主题和模型。
4. 点击“开始生成”。
5. 生成完成后下载 MP4。

## 输出位置

Web 任务产物默认写入：

```text
output/web_demo/
```

上传文件默认写入：

```text
uploads/
```

## 注意

- 生成过程仍然调用项目原有的 `t2v produce` 流水线。
- `ecnu-plus` 通常更适合现场演示，速度更稳定。
- 真实教材生成可能需要数分钟，页面日志会持续刷新。
