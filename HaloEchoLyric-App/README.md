# HaloEchoLyric · 控制中心

把 **EchoMusic** 正在播放的歌词，实时同步到 **花再 Halo PixelBar** 像素屏的图形化控制中心。
界面风格参考 Tutools-Halo / EDIFIER TempoHub。

---

## 快速开始

### 方式一：直接用打包好的 EXE（推荐）

1. 双击 **`install.bat`**
   它会：把程序复制到 `%LOCALAPPDATA%\Programs\HaloEchoLyric`、创建桌面和开始菜单快捷方式、启动程序。
2. 在应用里点 **歌词 → 安装 / 更新 EchoMusic 插件**（把插件放进 EchoMusic 插件目录）。
3. 打开 EchoMusic → **插件管理** → 启用 **「Halo PixelBar 歌词桥」**。
4. 随便放首歌，屏幕就开始跟歌词了。

### 方式二：源码运行（开发用）

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run-dev.bat
```

---

## 界面说明

左侧边栏 7 个页面：

| 页面 | 内容 |
|---|---|
| **概览** | EchoMusic 正在播放 + 进度、Halo PixelBar 在线状态与 VID/PID、同步开关、歌词预览 |
| **歌词** | 完整时间轴（当前行高亮自动滚动）、插件安装、文字效果、对齐方式、滚动方向、歌词延迟 |
| **屏幕** | 自定义文字、屏幕纯色、9 种屏幕场景（UI 模式）、列宽/颜色/切歌提示等参数 |
| **灯光** | 氛围灯 6 种灯效、三级亮度、颜色、速度 |
| **设置** | 自动连接、开机自启、关闭行为、USB 诊断、日志目录、恢复默认、卸载 |
| **日志** | 实时运行日志 |
| **关于** | 版本信息 |

底部常驻显示 **设备在线 / 设备未连接**。

---

## 歌词显示模式

| 模式 | 说明 |
|---|---|
| **静态显示** | 文字不动，可选 左对齐 / 居中对齐 / 右对齐 / 两端对齐 |
| **滚动显示** | 文字滚动，可选 **右 → 左**（默认，推荐）/ 左 → 右 |

> **关于「下 → 上 / 上 → 下」**：界面里保留了这两个选项，但它们是**灰的**。
> 原因是硬件协议里根本不存在纵向滚动 —— 设备的文字布局只有 6 种：
> `滚动左→右 / 滚动右→左 / 左对齐 / 右对齐 / 居中 / 两端对齐`。
> 这不是软件没做，是设备固件不支持。

滚动用的是**设备自带硬件滚动**（不是程序模拟动画），所以平滑且自动循环，不会有翻页的卡顿感。

---

## 打包

双击 **`build.bat`**，产物是 `dist\HaloEchoLyric.exe`（约 21 MB，单文件、无控制台窗口）。

等价命令：

```bat
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name HaloEchoLyric --icon src\icon.ico ^
  --distpath dist --workpath build ^
  --add-data "src\ui;ui" --add-data "src\plugin;plugin" ^
  --collect-all webview --collect-all clr_loader ^
  --hidden-import clr --hidden-import pythonnet --hidden-import pystray ^
  src\app.py
```

### 打包技术要点（踩过的坑）

1. **必须显式 `gui="edgechromium"`**
   pywebview 不指定后端时会静默退化成 **IE11 内核**（MSHTML），现代 CSS（Grid、CSS 变量）直接失效。
   指定后需要 `pythonnet` + WebView2 运行时（Win11 自带）。
   判断方法：页面里的 `navigator.userAgent` 应含 `Edg/` 而不是光秃秃的 `AppleWebKit/537.36`。
2. **`--add-data` 的路径基准**
   用了 `--specpath` 之后相对路径会以 spec 所在目录为基准，导致 `src\ui` 找不到。build.bat 里没有用它。
3. **`--collect-all webview`**
   否则 pywebview 目录下的 `Microsoft.Web.WebView2.*.dll` 和 `WebView2Loader.dll` 不会被打包。

---

## 卸载

两种方式：

- **应用内**：设置 → 卸载 HaloEchoLyric（会清插件、自启项、配置目录，并删除程序自身）
- **脚本**：双击 **`uninstall.bat`**（程序被手动删掉时用这个，它不依赖程序本体）

清理范围：

| 位置 | 内容 |
|---|---|
| `%APPDATA%\echo-music\plugins\halo-pixelbar-lyric` | EchoMusic 插件 |
| `%APPDATA%\HaloEchoLyric` | 配置 + 日志 |
| `%LOCALAPPDATA%\Programs\HaloEchoLyric` | 程序本体 |
| 桌面 / 开始菜单 / 启动项 | 快捷方式 |

**不写注册表**，不动系统目录。

---

## 目录结构

```
HaloEchoLyric-App/
├── src/
│   ├── app.py              入口：pywebview 窗口 + JS↔Python API 桥
│   ├── icon.ico
│   ├── halo/
│   │   ├── hid.py          HID 协议层（文本/布局/UI模式/氛围灯/屏幕色）
│   │   ├── device.py       设备管理：扫描、连接、在线监测、自动重连
│   │   ├── engine.py       歌词引擎：数据源、时间轴、滚动策略
│   │   └── config.py       配置与日志
│   ├── ui/                 界面（HTML + CSS + 原生 JS，无框架）
│   └── plugin/             随包分发的 EchoMusic 插件
├── tools/
│   ├── window_shot.py      开发用：按窗口标题截图（只截该窗口）
│   └── make_icon.py        生成 icon.ico
├── docs/
│   └── 协议说明.md          HID 协议完整记录
├── build.bat               打包
├── install.bat             安装到本机
├── uninstall.bat           彻底清理
└── run-dev.bat             源码运行
```

---

## 技术栈

| 层 | 选型 |
|---|---|
| 界面 | HTML + CSS + 原生 JS（无框架，WebView2 渲染） |
| 外壳 | Python 3.13 + pywebview 6（frameless 窗口） |
| 硬件 | hidapi，USB HID 直驱 |
| 打包 | PyInstaller onefile |

---

## 已知限制

1. **不支持上下滚动** —— 设备固件只提供横向滚动（见上文）
2. **单包文本上限 55 字节 UTF-8**（约 18 个汉字）。超出的长句会自动退回分页，不会丢内容
3. **只走 USB**，蓝牙连接时像素屏不可控
4. **音效模式 / 硬件音量**未接入（这部分命令协议尚未解析出来）
5. **TempoHub 场景导入**未接入 —— TempoHub 的场景数据是加密的（`product_list.json` 为密文，
   预览图存在 pickle 缓存里），需要进一步逆向。当前「屏幕场景」提供的是设备原生的 9 种 UI 模式
6. 与 **Tutools-Halo 不能同时使用**（两边抢同一个 HID 设备）

## 行为说明

- **同时只能开一个实例**。重复启动不会开新窗口，而是把已有窗口唤到前台（含从托盘恢复）。
  两个实例会抢同一个 HID 设备、互相覆盖屏幕内容，所以做了互斥保护。
- **关闭主窗口 = 最小化到托盘**（默认）。托盘图标双击可恢复，右键菜单可退出。
  想改成直接退出：设置 → 关闭主窗口 → 退出程序。
- 退出时会**还原设备原本的 UI 模式**（如果之前因待机切过）。
- 之前用 bat 版本（`HaloEchoLyric` 项目里的 `start-sync.bat`）的话，**请先关掉它**，
  否则两个程序会抢设备。注意：即使黑框里没输出，进程也可能还在跑，
  用任务管理器确认一下没有 `python3.13.exe`。

