# Google 2FA Batch Changer — Windows Desktop / Windows 桌面版

<p align="center">
  <strong>Batch-rotate Google Authenticator (TOTP) 2FA keys with a desktop GUI.</strong><br>
  批量更换 Google 账号 Authenticator (TOTP) 2FA 密钥的中文桌面工具。
</p>

Built on top of [gui9595/Google-2FA-Batch-Changer](https://github.com/gui9595/Google-2FA-Batch-Changer) (which is based on [Leclee/Auto_All_System](https://github.com/Leclee/Auto_All_System)). This fork replaces the raw CLI script with a hardened desktop application.

---

## English

### What it does

Automates the repetitive part of rotating 2FA keys for many Google accounts: log in → navigate to the 2FA settings → replace the Authenticator key → verify the new key → save the result. Browser isolation is provided by [BitBrowser](https://www.bitbrowser.cn/) (fingerprint browser); the tool drives it over CDP with Playwright.

**Desktop highlights**

- Chinese single-window GUI: account import, connection check, concurrency & batch settings, start / safe-stop, live progress log
- **Crash-safe key handling** — a newly extracted key is encrypted to disk (Windows DPAPI, current user only) *before* it is submitted to Google; an interrupted run can never lose the new key
- **Fail-closed identity check** — the tool verifies the logged-in account matches the target account before touching anything
- **Conservative outcomes** — results that cannot be confirmed become "needs manual review", never silently "success"; reviewed accounts are never re-rotated automatically
- **Credential hygiene** — passwords, TOTP codes and keys are never written to logs or window remarks; exports containing secrets require explicit confirmation
- **Safe cleanup** — only the temporary browser windows created by the tool are closed/deleted; your own BitBrowser profiles are untouched

### Quick start (no Python needed)

1. Download `Google2FADesktop-v1.0.0-win64.zip` from the [Releases](../../releases) page and unzip it (keep the `_internal` folder next to the EXE).
2. Install, log in and open [BitBrowser](https://www.bitbrowser.cn/) with its Local API enabled (default port `54345`).
3. Run `Google2FADesktop.exe`, click **检测连接 / Check connection**.
4. Import an account file (UTF-8 plain text, one account per line):

   ```
   email----password----recovery-email----current-2FA-key
   ```

   The recovery email may be empty but the `----` separators must stay; passwords must not contain `----`. See [账号格式示例.txt](账号格式示例.txt).
5. Click **开始轮换 / Start rotation** and confirm. Progress and failure reasons appear in the log pane.
6. When done, export results: "成功的新密钥" = new keys (CSV); "完整账号" = full account file with new keys.

### Safety notes (read once, seriously)

- **Only operate accounts you are authorized to manage.** Rotating a key invalidates the old one — import the new key into your authenticator app immediately.
- The recovery vault (`%LOCALAPPDATA%\Google2FADesktop\recovery.bin`) is bound to the current Windows user. Don't copy it to other machines and expect it to decrypt.
- Plaintext exports contain working credentials. Store them in a protected location and delete them when finished.
- Google may interpose extra verification (SMS, security key). The tool detects the backup-code challenge and switches to the Authenticator path automatically; for anything else it waits and tells you to finish that step manually in the browser window.
- The system clock must be accurate (TOTP tolerance is ±30 s).

### Build from source

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-build.txt
python -m unittest discover -s tests -v      # 45 offline tests, no real accounts
.\build-desktop.ps1                          # → dist\Google2FADesktop\
```

Requires Python 3.10+ (3.12 tested) and Windows 10/11. `build-desktop.ps1` runs tests, dependency checks and PyInstaller.

### Status & disclaimer

- The full rotation flow has been verified end-to-end against one real account (login → backup-code switch → TOTP → key replacement). Google UI changes can break selectors at any time; failure reasons are shown in the log to make such breakages diagnosable.
- For learning and internal operations use only. You are responsible for complying with Google's Terms of Service. The upstream project carries no license; all rights remain with its authors.

---

## 中文

### 这是干什么的

批量更换大量 Google 账号的 Authenticator (TOTP) 2FA 密钥：自动登录 → 进入 2FA 设置 → 更换密钥 → 验证新密钥 → 保存结果。浏览器隔离由 [BitBrowser](https://www.bitbrowser.cn/)（比特浏览器）提供，工具通过 CDP + Playwright 驱动。

### 桌面版特性

- 中文单窗口操作：账号导入、连接检测、并发/批量设置、开始、安全停止、实时进度日志
- **密钥防丢**：新密钥在提交 Google 之前先用 Windows DPAPI（仅当前用户可解密）落盘；中途断电、崩溃都不会丢
- **身份复核**：动密钥前先确认当前登录的就是目标账号；确认不了就不动手
- **结果保守**：无法确认的结果标"待人工核对"，绝不假装成功；已核对账号不会被再次自动轮换
- **凭据卫生**：密码、验证码、密钥不进日志、不写窗口备注；含密钥的导出需要二次确认
- **只清理自己**：只关闭/删除本工具创建的临时窗口，你自己 BitBrowser 里的配置绝不碰

### 快速开始（免 Python）

1. 到 [Releases](../../releases) 下载 `Google2FADesktop-v1.0.0-win64.zip` 解压（`_internal` 文件夹必须和 EXE 在一起）。
2. 安装并登录 [比特浏览器](https://www.bitbrowser.cn/)，开启 Local API（默认端口 `54345`）。
3. 运行 `Google2FADesktop.exe`，点 **检测连接**。
4. 导入账号文件（UTF-8 文本，每行一个账号）：

   ```
   邮箱----密码----辅助邮箱----当前2FA密钥
   ```

   辅助邮箱可留空但 `----` 分隔符必须保留；密码里不能出现 `----`。格式详见 [账号格式示例.txt](账号格式示例.txt)。
5. 点 **开始轮换** 并确认。日志窗格会显示每一步进度和失败原因。
6. 完成后导出：**成功的新密钥**（CSV）或 **完整账号（含密码）**（兼容原格式）。

### 安全须知（务必读一遍）

- **只操作你有权管理的账号**。轮换会使旧密钥立即失效，成功后请立刻把新密钥导入手机上的验证器 App。
- 加密恢复记录绑定当前 Windows 用户，换电脑/换用户解不开，不要删除或迁移。
- 明文导出文件等于可用凭据，请放受保护位置、用完删除。
- Google 若弹出短信、安全密钥等额外验证：工具会自动处理备用码页（点 Try another way → 选 Authenticator）；其他情况它会在日志里告诉你去浏览器里人工点一下，完成后自动继续。
- 系统时间必须准确（TOTP 误差 ≤30 秒），建议开启 Windows 自动校时。

### 从源码构建

见上方 English → Build from source，命令相同。详细操作手册见 [使用说明.txt](使用说明.txt)。

### 状态与免责

- 已用一个真实账号完整验证（登录 → 备用码切换 → TOTP → 换钥 → 验证成功）。Google 页面随时可能改版，选择器失效时日志会给出失败原因便于定位。
- 仅供学习与内部运营使用，使用产生的合规责任由使用者自行承担；上游项目未附带开源许可证，相关权利归其作者所有。
