import csv
import io

from .core import STATUSES


def render_export(kind, accounts, records):
    if kind == "full":
        if not accounts:
            raise ValueError("请先导入原账号文件")
        lines = []
        for account in accounts:
            entry = records.get(account.email, {})
            if entry.get("status") in {"review", "running"}:
                raise ValueError("存在待核对账号，不能导出可能误用旧密钥的完整账号文件")
            key = entry.get("key") if entry.get("status") == "success" else account.secret
            if not key:
                raise ValueError("成功记录缺少密钥，请人工核对")
            lines.append("----".join((account.email, account.password, account.recovery_email, key)))
        return "\n".join(lines) + "\n"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    if kind == "summary":
        writer.writerow(["邮箱", "状态", "更新时间（UTC）"])
        for email in sorted({a.email for a in accounts} | records.keys()):
            entry = records.get(email, {})
            # Prevent spreadsheet formula injection from untrusted account names.
            safe_email = "'" + email if email.startswith(("=", "+", "-", "@")) else email
            writer.writerow([safe_email, STATUSES.get(entry.get("status"), "待处理"), entry.get("updated", "")])
    elif kind in {"keys", "recovery"}:
        writer.writerow(["邮箱", "状态", "新密钥（待核对状态不代表已生效）"])
        for email, entry in sorted(records.items()):
            if entry.get("key") and (kind == "recovery" or entry["status"] == "success"):
                safe_email = "'" + email if email.startswith(("=", "+", "-", "@")) else email
                writer.writerow([safe_email, STATUSES.get(entry["status"], "待人工核对"), entry["key"]])
    else:
        raise ValueError("未知导出类型")
    return stream.getvalue()
