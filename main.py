import os
import sys
import re
import shutil
import threading
import subprocess
import urllib.request
import webbrowser
import customtkinter as ctk
from tkinter import filedialog, messagebox


APP_NAME = "MediaLoader Pro"

# ЗАМЕНИ НА СВОЮ ССЫЛКУ ДОНАТА
DONATE_LINK = "https://dalink.to/xz386"


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(get_app_dir(), name)


def bin_dir():
    path = os.path.join(get_app_dir(), "bin")
    os.makedirs(path, exist_ok=True)
    return path


def ytdlp_path():
    return os.path.join(bin_dir(), "yt-dlp.exe")


def install_ffmpeg():
    for name in ["ffmpeg.exe", "ffprobe.exe"]:
        src = resource_path(name)
        dst = os.path.join(bin_dir(), name)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)

    ffmpeg = os.path.join(bin_dir(), "ffmpeg.exe")
    return bin_dir() if os.path.exists(ffmpeg) else None


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

        self.build_ui()
        self.bind_all("<Control-KeyPress>", self.hotkeys)
        self.refresh_tools()

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

        ctk.CTkButton(
            tools,
            text="Установить / обновить yt-dlp",
            command=self.update_ytdlp,
            width=230
        ).grid(row=0, column=0, padx=8)

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
        ff = "FFmpeg ✅" if self.ffmpeg else "FFmpeg ❌"
        yd = "yt-dlp ✅" if os.path.exists(ytdlp_path()) else "yt-dlp ❌"

        ok = self.ffmpeg and os.path.exists(ytdlp_path())
        self.tools_label.configure(
            text=f"{ff} | {yd}",
            text_color="lightgreen" if ok else "orange"
        )

    def update_ytdlp(self):
        def run():
            try:
                self.after(0, lambda: self.status_label.configure(text="Скачиваю yt-dlp..."))

                url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
                urllib.request.urlretrieve(url, ytdlp_path())

                self.after(0, lambda: self.status_label.configure(text="yt-dlp установлен / обновлён ✅"))
                self.after(0, self.refresh_tools)

            except Exception as e:
                self.after(0, lambda: self.status_label.configure(text=f"Ошибка yt-dlp: {e}"))

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

    def start_download(self):
        if not os.path.exists(ytdlp_path()):
            messagebox.showwarning("yt-dlp не найден", "Нажми 'Установить / обновить yt-dlp'")
            return

        url = self.url_entry.get().strip()
        if not url:
            self.status_label.configure(text="Вставь ссылку")
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

            for line in process.stdout:
                line = line.strip()
                if line:
                    self.parse_progress(line)

            code = process.wait()

            if code != 0:
                raise Exception("yt-dlp завершился с ошибкой")

            self.after(0, lambda: self.progress.set(1))
            self.after(0, lambda: self.percent_label.configure(text="100%"))
            self.after(0, lambda: self.status_label.configure(text="Готово ✅"))
            self.after(0, lambda: self.speed_label.configure(text="Скорость: — | Осталось: —"))
            self.after(0, lambda: self.add_history(f"✅ {url}"))
            self.after(0, self.maybe_show_donate_message)

        except Exception as e:
            self.after(0, lambda: self.status_label.configure(text=f"Ошибка: {e}"))
            self.after(0, lambda: self.add_history(f"❌ {url} | {e}"))

        finally:
            self.after(0, lambda: self.download_btn.configure(state="normal"))


if __name__ == "__main__":
    app = App()
    app.mainloop()
