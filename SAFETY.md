# 使用者注意事项 / User Safety Notes

## 中文（请先读完再用）

1. **只操作你有权管理的账号。** 本工具会真实修改 Google 账号的 Authenticator 密钥，轮换成功后旧密钥立即失效。
2. **成功后第一件事**：从工具导出新密钥（选“成功的新密钥”），立刻导入手机验证器 App（Google Authenticator → 添加账号 → 输入设置密钥）。不导入，下次登录过不了 2FA。
3. 每台电脑的加密恢复记录（`%LOCALAPPDATA%\Google2FADesktop\recovery.bin`）只绑定当前 Windows 用户，换机/换用户都无法解密，请勿删除。
4. 明文导出（“完整账号”、“成功的新密钥”）等于可登录凭据：放受保护目录、用完删除、不要发群聊。
5. 账号文件是明文密码，同样按凭据管理；不要上传到网盘或聊天工具。
6. 遇到 Google 弹出短信/安全密钥等验证：备用码页工具会自动切换到 Authenticator；其他情况按日志提示在浏览器里人工点选，点完工具自动继续。**不要强制关闭工具**，用“安全停止”。
7. 系统时间必须准确（TOTP 误差 ≤30 秒）。
8. 结果显示“待人工核对”时，先用导出的恢复密钥确认哪个密钥真实生效，再用“人工核对所选账号”确认，不要盲目重试。
9. 本工具不会上传账号数据到任何第三方；但它驱动浏览器访问 Google，账号行为本身由你负责。仅供学习与内部运营使用。

## English

1. **Only operate accounts you are authorized to manage.** A successful rotation invalidates the old key immediately.
2. **First thing after success:** export the new keys ("成功的新密钥") and import them into your authenticator app right away.
3. The encrypted recovery vault (`%LOCALAPPDATA%\Google2FADesktop\recovery.bin`) is bound to the current Windows user; it cannot be decrypted elsewhere.
4. Plaintext exports are working credentials — protect and delete them; never paste them into chats.
5. The account file contains plaintext passwords; treat it accordingly.
6. If Google shows SMS/security-key challenges, the tool auto-handles the backup-code page; otherwise it tells you what to finish manually in the browser. Use "safe stop" instead of force-closing.
7. Keep the system clock accurate (TOTP tolerance ±30 s).
8. "Needs manual review" results: verify which key actually works before confirming; never blind-retry.
9. The tool uploads nothing to third parties, but you are responsible for the browser activity it performs. For learning and internal operations only.
