import asyncio
import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .backend import BrowserExecutor, check_connection, cleanup_temp_sessions, make_api
from .core import STATUSES, parse_accounts
from .exports import render_export
from .runner import run_accounts
from .storage import Vault, data_directory


class App:
    def __init__(self, root, vault=None):
        self.root = root
        self.vault = vault if vault is not None else Vault()
        self.accounts = []
        self.input_path = None
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.closing = False
        self.rows = {}
        self.states = {}
        self.worker = None
        self.poll_id = None
        root.title("Google 2FA · 密钥轮换工作台")
        root.geometry("1080x780")
        root.minsize(900, 680)
        root.configure(bg="#f2f5fa")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#f2f5fa")
        style.configure("TLabel", background="#f2f5fa", foreground="#22314b")
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background="#2563eb", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#91a6c6")])
        style.configure("Treeview", rowheight=32, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=8)
        style.configure("Horizontal.TProgressbar", background="#2563eb", troughcolor="#dfe7f3")
        self.build()
        self.show_records()
        self.append_log("就绪 · 先导入账号并检测 BitBrowser 连接。不会自动运行任务。")
        self.poll_id = root.after(150, self.poll)

    def build(self):
        header = tk.Frame(self.root, bg="#14243e", padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="Google 2FA", bg="#14243e", fg="white",
                 font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(header, text="密钥轮换工作台   /   本地加密恢复 · 安全停止 · 明确确认",
                 bg="#14243e", fg="#b8c9e5", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(5, 0))
        body = ttk.Frame(self.root, padding=22)
        body.pack(fill="both", expand=True)
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.import_button = ttk.Button(row, text="导入账号 TXT", command=self.import_file)
        self.import_button.pack(side="left")
        self.file_label = ttk.Label(row, text="未导入文件", width=32)
        self.file_label.pack(side="left", padx=12)
        ttk.Label(row, text="API 端口").pack(side="left", padx=(8, 4))
        self.port = tk.StringVar(value="54345")
        self.port_entry = ttk.Entry(row, textvariable=self.port, width=7)
        self.port_entry.pack(side="left")
        self.check_button = ttk.Button(row, text="检测连接", command=self.test_connection)
        self.check_button.pack(side="left", padx=8)
        self.connection_label = ttk.Label(row, text="尚未检测", foreground="#697b96")
        self.connection_label.pack(side="left")
        options = ttk.Frame(body)
        options.pack(fill="x", pady=(14, 14))
        ttk.Label(options, text="并发").pack(side="left")
        self.concurrency = tk.StringVar(value="1")
        self.concurrency_entry = ttk.Spinbox(options, from_=1, to=5, textvariable=self.concurrency, width=5)
        self.concurrency_entry.pack(side="left", padx=(6, 20))
        ttk.Label(options, text="每批数量").pack(side="left")
        self.batch_size = tk.StringVar(value="10")
        self.batch_entry = ttk.Spinbox(options, from_=1, to=100, textvariable=self.batch_size, width=6)
        self.batch_entry.pack(side="left", padx=6)
        self.start_button = ttk.Button(options, text="开始轮换", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="right")
        self.stop_button = ttk.Button(options, text="安全停止", command=self.request_stop, state="disabled")
        self.stop_button.pack(side="right", padx=8)
        self.help_button = ttk.Button(options, text="使用说明", command=self.help)
        self.help_button.pack(side="right", padx=4)
        self.metrics = ttk.Label(body, text="等待导入账号", font=("Microsoft YaHei UI", 11, "bold"))
        self.metrics.pack(anchor="w", pady=(0, 10))
        table_frame = ttk.Frame(body)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("email", "status"), show="headings", selectmode="browse")
        self.table.heading("email", text="账号邮箱（不展示密码或密钥）")
        self.table.heading("status", text="处理状态")
        self.table.column("email", width=560)
        self.table.column("status", width=220)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.tag_configure("success", foreground="#137346")
        self.table.tag_configure("skipped", foreground="#137346")
        self.table.tag_configure("review", foreground="#ab5b00")
        self.table.tag_configure("blocked", foreground="#ab5b00")
        self.table.tag_configure("failed", foreground="#b42318")
        self.progress = ttk.Progressbar(body, maximum=1)
        self.progress.pack(fill="x", pady=(12, 10))
        actions = ttk.Frame(body)
        actions.pack(fill="x")
        self.review_button = ttk.Button(actions, text="人工核对所选账号", command=self.review)
        self.review_button.pack(side="left")
        self.export_kind = ttk.Combobox(actions, state="readonly", width=21, values=(
            "结果摘要（不含密钥）", "成功的新密钥", "待核对密钥恢复", "完整账号（含密码）",
        ))
        self.export_kind.current(0)
        self.export_kind.pack(side="left", padx=(16, 6))
        self.export_button = ttk.Button(actions, text="导出…", command=self.export)
        self.export_button.pack(side="left")
        ttk.Button(actions, text="打开数据目录", command=self.open_data).pack(side="right")
        ttk.Label(body, text="运行日志 · 已过滤凭据；额外身份验证请在浏览器中人工处理",
                  foreground="#697b96").pack(anchor="w", pady=(16, 6))
        log_frame = ttk.Frame(body)
        log_frame.pack(fill="x")
        self.log = tk.Text(log_frame, height=6, bg="#e9eef6", fg="#334968", relief="flat",
                           padx=12, pady=8, font=("Microsoft YaHei UI", 9), state="disabled", wrap="word")
        self.log.pack(fill="x")
        ttk.Label(body, text="仅操作你有权管理的账号 · 关闭程序前请等待安全停止 · 恢复文件绑定当前 Windows 用户",
                  foreground="#697b96", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(10, 0))

    def append_log(self, message):
        stamped = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {message}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 600:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")
        try:
            # Persist the already-redacted lines so failures stay diagnosable.
            data_directory().mkdir(parents=True, exist_ok=True)
            with (data_directory() / "run.log").open("a", encoding="utf-8") as stream:
                stream.write(stamped + "\n")
        except OSError:
            pass

    def show_records(self):
        if self.rows:
            self.table.delete(*self.rows.values())
        self.rows, self.states = {}, {}
        records = self.vault.snapshot()
        emails = [a.email for a in self.accounts] if self.accounts else sorted(records)
        for email in emails:
            status = records.get(email, {}).get("status", "pending")
            if status == "running":
                status = "review"
            self.rows[email] = self.table.insert("", "end", values=(email, STATUSES[status]), tags=(status,))
            self.states[email] = status
        self.update_metrics()

    def update_metrics(self):
        total = len(self.rows)
        success = sum(s in {"success", "skipped"} for s in self.states.values())
        review = sum(s in {"review", "blocked"} for s in self.states.values())
        failed = sum(s == "failed" for s in self.states.values())
        finished = sum(s not in {"pending", "running"} for s in self.states.values())
        self.metrics.configure(text=f"共 {total} 个账号     成功 / 已跳过 {success}     失败 {failed}     待核对 {review}")
        self.progress.configure(maximum=max(total, 1), value=finished)

    def load_text(self, text):
        self.accounts = parse_accounts(text)
        self.show_records()
        self.append_log(f"已载入 {len(self.accounts)} 个账号；密码与密钥仅用于本次运行，不写入界面日志。")

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择账号文件", filetypes=[("账号文本", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            if Path(path).stat().st_size > 10 * 1024 * 1024:
                raise ValueError("文件超过 10 MB，请拆分后导入")
            self.load_text(Path(path).read_text(encoding="utf-8-sig"))
            self.input_path = Path(path).resolve()
            self.file_label.configure(text=f"已导入 {len(self.accounts)} 个账号")
        except UnicodeError:
            messagebox.showerror("导入失败", "请将账号文件保存为 UTF-8 编码后重试", parent=self.root)
        except ValueError as error:
            messagebox.showerror("导入失败", str(error), parent=self.root)
        except OSError:
            messagebox.showerror("导入失败", "无法读取文件，请检查权限和文件占用", parent=self.root)

    def configuration(self):
        try:
            port, concurrency, batch = int(self.port.get()), int(self.concurrency.get()), int(self.batch_size.get())
        except ValueError:
            raise ValueError("端口、并发及每批数量须为整数") from None
        if not 1 <= port <= 65535 or not 1 <= concurrency <= 5 or not 1 <= batch <= 100:
            raise ValueError("端口须为 1–65535，并发 1–5，每批数量 1–100")
        return port, concurrency, batch

    def set_busy(self, value):
        self.busy = value
        for widget in (
            self.import_button, self.check_button, self.start_button,
            self.port_entry, self.concurrency_entry, self.batch_entry,
            self.review_button, self.export_button,
        ):
            widget.configure(state="disabled" if value else "normal")
        self.stop_button.configure(state="normal" if value else "disabled")

    def test_connection(self):
        try:
            port, _, _ = self.configuration()
        except ValueError as error:
            messagebox.showerror("配置错误", str(error), parent=self.root)
            return
        self.connection_label.configure(text="检测中…")
        self.check_button.configure(state="disabled")

        def worker():
            try:
                asyncio.run(check_connection(make_api(port)))
                connected = True
            except Exception:
                connected = False
            self.events.put({"type": "connection", "success": connected})
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        if self.busy:
            return
        if not self.accounts:
            messagebox.showwarning("未导入账号", "请先导入账号 TXT 文件", parent=self.root)
            return
        try:
            port, concurrency, batch = self.configuration()
        except ValueError as error:
            messagebox.showerror("配置错误", str(error), parent=self.root)
            return
        if not messagebox.askyesno(
            "确认更换 Authenticator 密钥",
            f"将处理导入的 {len(self.accounts)} 个账号。\n\n"
            "此操作会使成功账号的旧 Authenticator 密钥失效。请确认你有管理权限，"
            "且已保留备用登录方式。\n已成功和待核对账号会自动跳过。\n\n是否继续？",
            parent=self.root, default="no",
        ):
            return
        self.stop.clear()
        self.set_busy(True)
        self.show_records()
        accounts = list(self.accounts)

        async def work():
            api = make_api(port)
            removed = await cleanup_temp_sessions(api)
            if removed:
                self.events.put({"type": "log", "message": f"已清理 {removed} 个本工具遗留的临时窗口。"})
            await check_connection(api)
            self.events.put({"type": "connection", "success": True})
            await run_accounts(accounts, self.vault, BrowserExecutor(api), self.events.put,
                               self.stop, concurrency=concurrency, batch_size=batch)

        def worker():
            try:
                asyncio.run(work())
            except ConnectionError:
                self.events.put({"type": "connection", "success": False})
                self.events.put({"type": "log", "message": "连接失败：请安装并登录 BitBrowser，启动 Local API 后重试。"})
            except Exception as error:
                self.events.put({"type": "log", "message": f"任务未能继续（{type(error).__name__}）。请保留恢复记录并检查环境。"})
            finally:
                self.events.put({"type": "finished"})
        self.worker = threading.Thread(target=worker, daemon=False)
        self.worker.start()
        self.append_log("任务启动；如遇手机、安全密钥等验证，请在浏览器中人工完成。")

    def request_stop(self):
        self.stop.set()
        self.stop_button.configure(state="disabled")
        self.append_log("已停止调度新账号；正在处理的账号会继续至安全结束并保存结果，请勿强制关闭。")

    def poll(self):
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        for _ in range(300):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event["type"]
            if kind == "log":
                self.append_log(event["message"])
            elif kind == "status" and event["email"] in self.rows:
                email, status = event["email"], event["status"]
                self.states[email] = status
                self.table.item(self.rows[email], values=(email, STATUSES[status]), tags=(status,))
                self.update_metrics()
                if status in {"success", "failed", "review", "blocked"}:
                    self.append_log(f"{email} · {STATUSES[status]}")
            elif kind == "connection":
                connected = event["success"]
                self.connection_label.configure(text="已连接" if connected else "未连接 · 请启动 BitBrowser",
                                                foreground="#137346" if connected else "#b42318")
                if not self.busy:
                    self.check_button.configure(state="normal")
            elif kind == "finished":
                self.set_busy(False)
                self.append_log("本轮调度已结束。请检查失败 / 待核对状态，并按需导出结果。")
                if self.closing:
                    self.root.destroy()
                    return
        self.poll_id = self.root.after(150, self.poll)

    def review(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("人工核对", "请先选择一个待核对账号", parent=self.root)
            return
        email = self.table.item(selected[0], "values")[0]
        record = self.vault.get(email)
        if not record or record["status"] not in {"review", "running"}:
            messagebox.showinfo("无需核对", "仅待核对或中断的记录可人工确认", parent=self.root)
            return
        answer = messagebox.askyesnocancel(
            "确认核对结果",
            "请先导出“待核对密钥恢复”，在 Google 中人工检查实际生效密钥。\n\n"
            "是：我已验证新密钥有效，标记成功。\n"
            "否：我已验证旧密钥仍有效，允许重新处理。\n"
            "取消：保持待核对，不做修改。",
            parent=self.root, default="cancel",
        )
        if answer is None:
            return
        if answer and not record.get("key"):
            messagebox.showwarning("无法标记成功", "没有可恢复的新密钥，请先人工确认账号安全状态。", parent=self.root)
            return
        phrase = "已验证新密钥" if answer else "已验证旧密钥"
        typed = simpledialog.askstring("再次确认", f"为 {email}\n请输入“{phrase}”确认：", parent=self.root)
        if typed != phrase:
            return
        try:
            self.vault.put(email, "success" if answer else "failed", key=record.get("key"))
            self.show_records()
            self.append_log(f"{email} · 已按人工核对结果更新。")
        except Exception:
            messagebox.showerror("保存失败", "未能保存人工核对结果，状态未更改", parent=self.root)

    def export(self):
        kinds = ("summary", "keys", "recovery", "full")
        kind = kinds[self.export_kind.current()]
        try:
            content = render_export(kind, self.accounts, self.vault.snapshot())
        except ValueError as error:
            messagebox.showwarning("暂不能导出", str(error), parent=self.root)
            return
        if kind != "summary" and not messagebox.askyesno(
            "敏感数据明文导出",
            "导出文件将包含可用于登录的 2FA 密钥，完整账号还包含密码。\n"
            "任何能读取文件的人都可能使用这些凭据。请保存到受保护位置，用完后妥善处理。\n\n确认导出？",
            parent=self.root, default="no",
        ):
            return
        suffix = ".txt" if kind == "full" else ".csv"
        path = filedialog.asksaveasfilename(
            parent=self.root, title="导出到新文件（不覆盖原文件）", defaultextension=suffix,
            initialfile=f"2fa_{kind}_{datetime.now():%Y%m%d_%H%M%S}{suffix}",
            filetypes=[("导出文件", "*" + suffix)],
        )
        if not path:
            return
        try:
            destination = Path(path).resolve()
            if destination == self.input_path or destination == self.vault.path.resolve():
                raise ValueError("不能覆盖账号输入文件或加密恢复记录")
            with destination.open("x", encoding="utf-8-sig", newline="") as stream:
                stream.write(content)
            self.append_log("已导出到所选新文件。")
            messagebox.showinfo("已导出", "导出完成。含密钥的文件请妥善保管。", parent=self.root)
        except FileExistsError:
            messagebox.showwarning("文件已存在", "为防止误覆盖，请选择一个新的文件名。", parent=self.root)
        except (OSError, ValueError):
            messagebox.showerror("导出失败", "无法写入或目标受保护，请选择其他新文件。", parent=self.root)

    def open_data(self):
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        os.startfile(str(directory))

    def help(self):
        window = tk.Toplevel(self.root)
        window.title("使用说明与环境准备")
        window.geometry("720x520")
        text = tk.Text(window, wrap="word", font=("Microsoft YaHei UI", 11), padx=22, pady=18)
        text.pack(fill="both", expand=True)
        text.insert("1.0",
            "1. 安装并登录 BitBrowser，开启 Local API（默认端口 54345）。\n"
            "2. 确认网络可访问 Google，并开启 Windows 自动校时。\n"
            "3. 准备 UTF-8 TXT，每行格式：\n邮箱----密码----辅助邮箱----旧2FA密钥\n"
            "辅助邮箱可留空，但分隔符必须保留；密码中不能包含 ----。\n"
            "4. 导入文件 → 检测连接 → 开始轮换。首次建议只处理一个授权账号。\n"
            "5. 遇到手机验证或安全密钥提示，请在 BitBrowser 窗口手动处理；"
            "不要强制关闭程序。点击安全停止只停止后续调度。\n"
            "6. 已成功账号自动跳过。待核对账号须先导出恢复密钥并确认实际生效密钥，"
            "再通过“人工核对所选账号”确认；不确定时不要重试。\n\n"
            "导出范围：摘要和密钥导出包含本 Windows 用户的全部本工具历史记录；"
            "完整账号导出只包含当前导入账号。\n\n"
            "恢复记录：%LOCALAPPDATA%\\Google2FADesktop\\recovery.bin\n"
            "使用 Windows DPAPI 加密，绑定当前 Windows 用户，不保存账号密码。"
            "请勿删除或迁移后假设可在其他用户下解密。\n\n"
            "本工具不会上传账号到额外服务；浏览器仍会访问 Google，BitBrowser 自身的数据处理"
            "由其产品和配置决定。打包免装 Python，不代表免装 BitBrowser。\n"
            "真实 Google 页面可能变化；离线测试不代表在线轮换已经验证。")
        text.configure(state="disabled")
        ttk.Button(window, text="打开 BitBrowser 官方下载页",
                   command=lambda: webbrowser.open("https://www.bitbrowser.cn/")).pack(pady=12)

    def close(self):
        if self.busy:
            if messagebox.askyesno("等待安全结束", "停止新任务并等待当前账号处理结束后关闭？", parent=self.root):
                self.closing = True
                self.request_stop()
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        self.root.destroy()
