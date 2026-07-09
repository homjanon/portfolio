# 金融资讯日报自动化部署包

## 版本
v22 — 结构优化（3部分）+ 宏观扩展（核心PCE/BDI/SOX等）

## 文件结构
```
automation-package/
├── README.md
├── prompt/
│   └── task_prompt_v21.txt      # LLM 日报生成提示词（含嵌入式 prefetch 脚本）
├── scripts/
│   ├── prefetch_data.py         # 数据预抓取脚本（独立运行）
│   ├── md_to_reader.py          # Markdown → HTML（公众号排版）
│   └── md_to_mp3.py             # Markdown → MP3（语音播报）
└── web/
    └── sw.js                    # 离线缓存 Service Worker
```

## 部署方式
1. 将 `prompt/task_prompt_v21.txt` 设置为自动化任务的提示词
2. 确保 `scripts/prefetch_data.py` 在自动化环境中可执行
3. 部署依赖：akshear、yfinance、requests、lxml、markdown、edge-tts
