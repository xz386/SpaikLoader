import os
import sys
import re
import shutil
import threading
import subprocess
import ssl
import tempfile
import zipfile
import urllib.request
import webbrowser
import customtkinter as ctk
from tkinter import filedialog, messagebox


APP_NAME = "MediaLoader Pro"

# ЗАМЕНИ НА СВОЮ ССЫЛКУ ДОНАТА
DONATE_LINK = "https://dalink.to/xz386"

# Источники для скачивания компонентов (проверены: отдают файл по редиректу GitHub)
YTDLP_URLS = [
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
]
FFMPEG_URLS = [
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
]
# yt-dlp требует JS-рантайм (Deno) для полноценной работы с YouTube
DENO_URLS = [
    "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpaikLoader"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(get_app_dir(), name)


def _is_writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return True
    except Exception:
        return False


_BIN_DIR = None


def bin_dir():
    """Папка bin рядом с программой, а если туда нельзя писать
    (например, Program Files) — %LOCALAPPDATA%\\SpaikLoader\\bin."""
    global _BIN_DIR
    if _BIN_DIR:
        return _BIN_DIR

    local = os.path.join(get_app_dir(), "bin")
    if _is_writable(local):
        _BIN_DIR = local
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        _BIN_DIR = os.path.join(base, "SpaikLoader", "bin")
        os.makedirs(_BIN_DIR, exist_ok=True)
    return _BIN_DIR


def find_tool(exe_name):
    """Ищем программу в bin, затем в PATH."""
    path = os.path.join(bin_dir(), exe_name)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    return shutil.which(exe_name)


def ytdlp_path():
    return find_tool("yt-dlp.exe")


def deno_path():
    return find_tool("deno.exe")


def install_ffmpeg():
    """Копирует встроенный в exe ffmpeg (если есть) в bin и возвращает
    папку с ffmpeg.exe или None."""
    for name in ["ffmpeg.exe", "ffprobe.exe"]:
        src = resource_path(name)
        dst = os.path.join(bin_dir(), name)
        try:
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
        except Exception:
            pass

    ffmpeg = find_tool("ffmpeg.exe")
    return os.path.dirname(ffmpeg) if ffmpeg else None


def _ssl_contexts():
    yield ssl.create_default_context()
    try:
        import certifi
        yield ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass


def _download_urllib(url, dest, progress):
    last_error = None
    for ctx in _ssl_contexts():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            if total and done != total:
                raise IOError(f"файл скачан не полностью ({done} из {total} байт)")
            return
        except ssl.SSLError as e:
            last_error = e
            continue
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError):
                last_error = e
                continue
            raise
    raise last_error


def _download_curl(url, dest):
    """Запасной вариант: встроенный в Windows 10/11 curl.exe
    (использует системные сертификаты и обычно проходит там, где Python не может)."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise IOError("curl не найден")
    subprocess.run(
        [curl, "-L", "--fail", "--retry", "3", "-A", USER_AGENT, "-o", dest, url],
        check=True,
        capture_output=True,
        creationflags=NO_WINDOW,
    )


def download_file(urls, dest, progress=None):
    """Скачивает первый рабочий URL во временный файл и атомарно переносит в dest."""
    errors = []
    tmp = dest + ".part"
    for url in urls:
        for method in ("urllib", "curl"):
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                if method == "urllib":
                    _download_urllib(url, tmp, progress)
                else:
                    _download_curl(url, tmp)
                if not os.path.exists(tmp) or os.path.getsize(tmp) < 1024:
                    raise IOError("получен пустой файл")
                os.replace(tmp, dest)
                return
            except Exception as e:
                errors.append(f"{method}: {e}")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
    raise IOError("не удалось скачать.\n" + "\n".join(errors[-4:]))


def latest_ytdlp_version():
    """Последняя версия yt-dlp на GitHub (по редиректу releases/latest -> /tag/<версия>)."""
    url = "https://github.com/yt-dlp/yt-dlp/releases/latest"
    for ctx in _ssl_contexts():
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                final = resp.geturl()
            if "/tag/" in final:
                return final.rsplit("/tag/", 1)[1].strip("/")
        except Exception:
            continue
    return None


def installed_ytdlp_version():
    path = ytdlp_path()
    if not path:
        return None
    try:
        out = subprocess.run(
            [path, "--version"], capture_output=True, text=True,
            timeout=60, creationflags=NO_WINDOW
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def extract_from_zip(zip_path, names, target_dir):
    """Достаёт из архива файлы с указанными именами (в любой подпапке)."""
    found = set()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = os.path.basename(info.filename).lower()
            if base in names and base not in found:
                dst = os.path.join(target_dir, base)
                tmp = dst + ".part"
                with z.open(info) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(tmp, dst)
                found.add(base)
    missing = set(names) - found
    if missing:
        raise IOError("в архиве нет: " + ", ".join(sorted(missing)))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("840x790")
        self.resizable(False, False)

        try:
            self.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.ffmpeg = install_ffmpeg()
        self.save_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        self.current_file = ""
        self.done_count = 0
        self.installing = False
        self.ytdlp_checked = False

        self.build_ui()
        self.bind_all("<Control-KeyPress>", self.hotkeys)
        self.refresh_tools()

        # При запуске сами докачиваем недостающее и обновляем yt-dlp
        self.after(500, lambda: self.install_components(on_done=lambda ok: None))

    def build_ui(self):
        tabs = ctk.CTkTabview(self, width=810, height=760)
        tabs.pack(padx=12, pady=12)

        tab_main = tabs.add("Скачать")
        tab_donate = tabs.add("Поддержать ❤️")
        tab_about = tabs.add("О программе")

        # =======================
        # TAB: MAIN
        # =======================
        ctk.CTkLabel(
            tab_main,
            text=APP_NAME,
            font=("Arial", 32, "bold")
        ).pack(pady=12)

        self.url_entry = ctk.CTkEntry(
            tab_main,
            width=690,
            height=42,
            placeholder_text="Вставь ссылку на видео или плейлист"
        )
        self.url_entry.pack(pady=8)

        buttons = ctk.CTkFrame(tab_main, fg_color="transparent")
        buttons.pack(pady=6)

        ctk.CTkButton(buttons, text="Вставить", command=self.paste, width=130).grid(row=0, column=0, padx=6)
        ctk.CTkButton(buttons, text="Очистить", command=lambda: self.url_entry.delete(0, "end"), width=130).grid(row=0, column=1, padx=6)
        ctk.CTkButton(buttons, text="Открыть папку", command=self.open_folder, width=150).grid(row=0, column=2, padx=6)

        options = ctk.CTkFrame(tab_main, fg_color="transparent")
        options.pack(pady=12)

        self.format_box = ctk.CTkOptionMenu(
            options,
            values=["MP4", "MP3"],
            command=self.change_format,
            width=150
        )
        self.format_box.set("MP4")
        self.format_box.grid(row=0, column=0, padx=10)

        self.quality_box = ctk.CTkOptionMenu(
            options,
            values=["360p", "480p", "720p", "1080p", "Лучшее"],
            width=150
        )
        self.quality_box.set("720p")
        self.quality_box.grid(row=0, column=1, padx=10)

        self.playlist_check = ctk.CTkCheckBox(options, text="Плейлист")
        self.playlist_check.grid(row=0, column=2, padx=10)

        folder_row = ctk.CTkFrame(tab_main, fg_color="transparent")
        folder_row.pack(pady=8)

        self.folder_label = ctk.CTkLabel(
            folder_row,
            text=f"Папка: {self.save_folder}",
            width=560,
            anchor="w"
        )
        self.folder_label.grid(row=0, column=0, padx=8)

        ctk.CTkButton(
            folder_row,
            text="Выбрать",
            command=self.choose_folder,
            width=110
        ).grid(row=0, column=1, padx=8)

        self.progress = ctk.CTkProgressBar(tab_main, width=690)
        self.progress.set(0)
        self.progress.pack(pady=16)

        self.percent_label = ctk.CTkLabel(tab_main, text="0%", font=("Arial", 16, "bold"))
        self.percent_label.pack(pady=2)

        self.status_label = ctk.CTkLabel(tab_main, text="Готов", font=("Arial", 14))
        self.status_label.pack(pady=4)

        self.speed_label = ctk.CTkLabel(tab_main, text="Скорость: — | Осталось: —", font=("Arial", 13))
        self.speed_label.pack(pady=2)

        self.file_label = ctk.CTkLabel(tab_main, text="Файл: —", font=("Arial", 12), text_color="gray")
        self.file_label.pack(pady=2)

        self.download_btn = ctk.CTkButton(
            tab_main,
            text="Скачать",
            command=self.start_download,
            width=260,
            height=48,
            font=("Arial", 17, "bold")
        )
        self.download_btn.pack(pady=14)

        tools = ctk.CTkFrame(tab_main, fg_color="transparent")
        tools.pack(pady=5)

        self.tools_btn = ctk.CTkButton(
            tools,
            text="Обновить yt-dlp / FFmpeg / Deno",
            command=self.update_ytdlp,
            width=230
        )
        self.tools_btn.grid(row=0, column=0, padx=8)

        self.tools_label = ctk.CTkLabel(tools, text="")
        self.tools_label.grid(row=0, column=1, padx=8)

        self.history = ctk.CTkTextbox(tab_main, width=690, height=125)
        self.history.pack(pady=10)
        self.history.insert("end", "История:\n")
        self.history.configure(state="disabled")

        ctk.CTkLabel(
            tab_main,
            text="Без галки скачивается только одно видео. Для плейлиста поставь галку и вставь ссылку с list=...",
            font=("Arial", 11),
            text_color="gray"
        ).pack(pady=5)

        # =======================
        # TAB: DONATE
        # =======================
        ctk.CTkLabel(
            tab_donate,
            text="Поддержать проект ❤️",
            font=("Arial", 30, "bold")
        ).pack(pady=28)

        ctk.CTkLabel(
            tab_donate,
            text="Программа бесплатная. Если она тебе помогла — можешь поддержать разработку.",
            font=("Arial", 15),
            wraplength=560,
            justify="center"
        ).pack(pady=10)

        donate_box = ctk.CTkFrame(tab_donate)
        donate_box.pack(pady=24, padx=40, fill="x")

        ctk.CTkLabel(
            donate_box,
            text="Спасибо за поддержку!",
            font=("Arial", 20, "bold")
        ).pack(pady=16)

        ctk.CTkButton(
            donate_box,
            text="💸 Поддержать через DonationAlerts",
            command=lambda: webbrowser.open(DONATE_LINK),
            width=300,
            height=48,
            font=("Arial", 15, "bold")
        ).pack(pady=8)

        ctk.CTkButton(
            donate_box,
            text="📋 Скопировать ссылку доната",
            command=lambda: self.copy_text(DONATE_LINK),
            width=300,
            height=40
        ).pack(pady=8)

        ctk.CTkLabel(
            donate_box,
            text=DONATE_LINK,
            font=("Arial", 12),
            text_color="gray",
            wraplength=560
        ).pack(pady=12)

        # =======================
        # TAB: ABOUT
        # =======================
        ctk.CTkLabel(
            tab_about,
            text="О программе",
            font=("Arial", 28, "bold")
        ).pack(pady=25)

        about_text = (
            "MediaLoader Pro — простая программа для скачивания видео и музыки.\n\n"
            "Возможности:\n"
            "• MP4 видео со звуком\n"
            "• MP3 с тегами и обложкой\n"
            "• выбор качества видео\n"
            "• поддержка плейлистов\n"
            "• прогресс, скорость и время до конца\n\n"
            "Скачивай только тот контент, на который у тебя есть права."
        )

        ctk.CTkLabel(
            tab_about,
            text=about_text,
            font=("Arial", 15),
            justify="left",
            wraplength=620
        ).pack(pady=10)

    def hotkeys(self, event):
        code = event.keycode

        if code == 86:
            return self.paste()
        if code == 67:
            return self.copy()
        if code == 88:
            return self.cut()

    def paste(self, event=None):
        try:
            text = self.clipboard_get().strip()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, text)
            self.status_label.configure(text="Ссылка вставлена ✅")
        except Exception:
            self.status_label.configure(text="Буфер пуст")
        return "break"

    def copy(self, event=None):
        self.clipboard_clear()
        self.clipboard_append(self.url_entry.get())
        return "break"

    def cut(self, event=None):
        self.copy()
        self.url_entry.delete(0, "end")
        return "break"

    def copy_text(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        try:
            self.status_label.configure(text="Ссылка скопирована ✅")
        except Exception:
            pass
        messagebox.showinfo("Готово", "Ссылка скопирована")

    def change_format(self, value):
        self.quality_box.configure(state="disabled" if value == "MP3" else "normal")

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.save_folder = folder
            self.folder_label.configure(text=f"Папка: {self.save_folder}")

    def open_folder(self):
        os.makedirs(self.save_folder, exist_ok=True)
        os.startfile(self.save_folder)

    def refresh_tools(self):
        self.ffmpeg = install_ffmpeg()
        has_yt = bool(ytdlp_path())
        has_deno = bool(deno_path())

        ff = "FFmpeg ✅" if self.ffmpeg else "FFmpeg ❌"
        yd = "yt-dlp ✅" if has_yt else "yt-dlp ❌"
        dn = "Deno ✅" if has_deno else "Deno ❌"

        ok = self.ffmpeg and has_yt and has_deno
        self.tools_label.configure(
            text=f"{ff} | {yd} | {dn}",
            text_color="lightgreen" if ok else "orange"
        )

    def set_status(self, text):
        self.after(0, lambda t=text: self.status_label.configure(text=t))

    def _progress_cb(self, title):
        def cb(done, total):
            if total:
                p = done / total
                self.after(0, lambda p=p: self.progress.set(p))
                self.after(0, lambda p=p: self.percent_label.configure(text=f"{int(p * 100)}%"))
                self.set_status(f"{title}: {done // 1048576} / {total // 1048576} МБ")
            else:
                self.set_status(f"{title}: {done // 1048576} МБ")
        return cb

    def update_ytdlp(self):
        """Кнопка: скачать последние версии всех компонентов."""
        self.install_components(force=True)

    def install_components(self, force=False, on_done=None):
        """Скачивает компоненты в фоне.
        force=True  — перекачать последние версии всего (yt-dlp, FFmpeg, Deno);
        force=False — скачать только недостающее и обновить yt-dlp, если вышла новая версия.
        on_done(ok) вызывается в потоке интерфейса по окончании."""
        if self.installing:
            return
        self.installing = True
        self.tools_btn.configure(state="disabled")
        self.download_btn.configure(state="disabled")

        def run():
            errors = []
            target = bin_dir()

            # 1. yt-dlp — качаем, если нет, если force или вышла новая версия
            need_yt = force or not ytdlp_path()
            if not need_yt:
                self.set_status("Проверяю обновления yt-dlp...")
                latest = latest_ytdlp_version()
                current = installed_ytdlp_version()
                need_yt = bool(latest and current and latest != current)
            if need_yt:
                try:
                    download_file(
                        YTDLP_URLS,
                        os.path.join(target, "yt-dlp.exe"),
                        self._progress_cb("Скачиваю последнюю версию yt-dlp")
                    )
                except Exception as e:
                    errors.append(f"yt-dlp: {e}")
            self.ytdlp_checked = True

            # 2. FFmpeg (архив ~200 МБ)
            if force or not install_ffmpeg():
                zip_path = os.path.join(tempfile.gettempdir(), "spaikloader_ffmpeg.zip")
                try:
                    download_file(FFMPEG_URLS, zip_path, self._progress_cb("Скачиваю FFmpeg"))
                    self.set_status("Распаковываю FFmpeg...")
                    extract_from_zip(zip_path, {"ffmpeg.exe", "ffprobe.exe"}, target)
                except Exception as e:
                    errors.append(f"FFmpeg: {e}")
                finally:
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass

            # 3. Deno — JS-рантайм, нужен yt-dlp для YouTube
            if force or not deno_path():
                zip_path = os.path.join(tempfile.gettempdir(), "spaikloader_deno.zip")
                try:
                    download_file(DENO_URLS, zip_path, self._progress_cb("Скачиваю Deno"))
                    self.set_status("Распаковываю Deno...")
                    extract_from_zip(zip_path, {"deno.exe"}, target)
                except Exception as e:
                    errors.append(f"Deno: {e}")
                finally:
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass

            def finish():
                self.installing = False
                self.refresh_tools()
                self.progress.set(0)
                self.percent_label.configure(text="0%")
                self.tools_btn.configure(state="normal")
                self.download_btn.configure(state="normal")
                if not errors:
                    self.status_label.configure(text="Компоненты готовы ✅")
                if on_done:
                    on_done(not errors)
                    if not errors:
                        return
                if errors:
                    msg = "\n\n".join(errors)
                    self.status_label.configure(text="Ошибка установки компонентов ❌")
                    self.add_history("❌ Установка: " + msg.replace("\n", " "))
                    messagebox.showerror(
                        "Ошибка установки",
                        msg + "\n\nПроверь интернет / антивирус (он может удалять yt-dlp.exe) "
                        f"и попробуй ещё раз.\nПапка компонентов: {bin_dir()}"
                    )
                else:
                    self.status_label.configure(text="Компоненты установлены / обновлены ✅")

            self.after(0, finish)

        threading.Thread(target=run, daemon=True).start()

    def add_history(self, text):
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n")
        self.history.see("end")
        self.history.configure(state="disabled")

    def maybe_show_donate_message(self):
        self.done_count += 1

        if self.done_count in [3, 8, 15]:
            messagebox.showinfo(
                "Спасибо за использование ❤️",
                "Если программа тебе полезна — можешь поддержать проект во вкладке 'Поддержать ❤️'."
            )

    def start_download(self, skip_install=False):
        url = self.url_entry.get().strip()
        if not url:
            self.status_label.configure(text="Вставь ссылку")
            return

        if self.installing:
            self.status_label.configure(text="Подожди, идёт установка компонентов...")
            return

        # Нет компонентов или yt-dlp ещё не проверялся на обновление в этом запуске —
        # сначала сами скачиваем последние версии, потом сразу начинаем загрузку.
        need_mp3_ffmpeg = self.format_box.get() == "MP3" and not self.ffmpeg
        needs = not ytdlp_path() or not deno_path() or need_mp3_ffmpeg or not self.ytdlp_checked
        if needs and not skip_install:
            def after_install(ok):
                # Даже если что-то второстепенное не скачалось, но yt-dlp есть — качаем.
                if ytdlp_path():
                    self.start_download(skip_install=True)
            self.install_components(on_done=after_install)
            return

        if not ytdlp_path():
            messagebox.showwarning("yt-dlp не найден", "Не удалось скачать yt-dlp. Проверь интернет и нажми 'Обновить'.")
            return

        self.download_btn.configure(state="disabled")
        self.progress.set(0)
        self.percent_label.configure(text="0%")
        self.speed_label.configure(text="Скорость: — | Осталось: —")
        self.file_label.configure(text="Файл: —")
        self.status_label.configure(text="Запуск...")

        threading.Thread(target=self.download, args=(url,), daemon=True).start()

    def parse_progress(self, line):
        if "[download] Destination:" in line:
            self.current_file = line.split("Destination:", 1)[1].strip()
            name = os.path.basename(self.current_file)
            self.after(0, lambda: self.file_label.configure(text=f"Файл: {name}"))

        if "[download]" not in line or "%" not in line:
            return

        match = re.search(
            r"(\d+(?:\.\d+)?)%.*?at\s+([^\s]+(?:\s*[A-Za-z/]+)?)\s+ETA\s+([0-9:]+)",
            line
        )

        if match:
            percent = float(match.group(1))
            speed = match.group(2).strip()
            eta = match.group(3).strip()

            self.after(0, lambda p=percent: self.progress.set(p / 100))
            self.after(0, lambda p=percent: self.percent_label.configure(text=f"{int(p)}%"))
            self.after(0, lambda s=speed, e=eta: self.speed_label.configure(text=f"Скорость: {s} | Осталось: {e}"))
            self.after(0, lambda p=percent: self.status_label.configure(text=f"Скачивание: {int(p)}%"))
            return

        match_simple = re.search(r"(\d+(?:\.\d+)?)%", line)
        if match_simple:
            percent = float(match_simple.group(1))
            self.after(0, lambda p=percent: self.progress.set(p / 100))
            self.after(0, lambda p=percent: self.percent_label.configure(text=f"{int(p)}%"))
            self.after(0, lambda p=percent: self.status_label.configure(text=f"Скачивание: {int(p)}%"))

    def download(self, url):
        try:
            # Плейлист качается ТОЛЬКО если стоит галка.
            is_playlist = self.playlist_check.get() == 1

            fmt = self.format_box.get()
            quality = self.quality_box.get()

            if is_playlist:
                out = os.path.join(
                    self.save_folder,
                    "%(playlist_title)s",
                    "%(playlist_index)03d - %(title)s.%(ext)s"
                )
                playlist_arg = "--yes-playlist"
            else:
                out = os.path.join(self.save_folder, "%(title)s.%(ext)s")
                playlist_arg = "--no-playlist"

            cmd = [
                ytdlp_path(),
                playlist_arg,
                "--newline",
                "--windows-filenames",
                "--retries", "10",
                "--fragment-retries", "10",
                "-o", out,
            ]

            if self.ffmpeg:
                cmd += ["--ffmpeg-location", self.ffmpeg]

            deno = deno_path()
            if deno:
                cmd += ["--js-runtimes", f"deno:{deno}"]

            if fmt == "MP3":
                if not self.ffmpeg:
                    raise Exception("Для MP3 нужен ffmpeg.exe")

                cmd += [
                    "-f", "bestaudio/best",
                    "-x",
                    "--audio-format", "mp3",
                    "--audio-quality", "192K",
                    "--embed-metadata",
                    "--embed-thumbnail",
                    "--convert-thumbnails", "jpg",
                ]

            else:
                if quality == "Лучшее":
                    video_format = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                else:
                    h = quality.replace("p", "")
                    video_format = (
                        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"best[height<={h}][ext=mp4]/best"
                    )

                cmd += [
                    "-f", video_format,
                    "--merge-output-format", "mp4",
                    "--embed-metadata",
                ]

            cmd.append(url)

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            last_error = ""
            for line in process.stdout:
                line = line.strip()
                if line:
                    if line.startswith("ERROR:"):
                        last_error = line[6:].strip()
                    self.parse_progress(line)

            code = process.wait()

            if code != 0:
                raise Exception(last_error or "yt-dlp завершился с ошибкой")

            self.after(0, lambda: self.progress.set(1))
            self.after(0, lambda: self.percent_label.configure(text="100%"))
            self.after(0, lambda: self.status_label.configure(text="Готово ✅"))
            self.after(0, lambda: self.speed_label.configure(text="Скорость: — | Осталось: —"))
            self.after(0, lambda: self.add_history(f"✅ {url}"))
            self.after(0, self.maybe_show_donate_message)

        except Exception as e:
            # e копируем в переменную: в Python 3 она удаляется после except,
            # и lambda, вызванная позже через after(), падала с NameError
            err = str(e)
            self.after(0, lambda: self.status_label.configure(text=f"Ошибка: {err[:120]}"))
            self.after(0, lambda: self.add_history(f"❌ {url} | {err}"))

        finally:
            self.after(0, lambda: self.download_btn.configure(state="normal"))


if __name__ == "__main__":
    app = App()
    app.mainloop()
