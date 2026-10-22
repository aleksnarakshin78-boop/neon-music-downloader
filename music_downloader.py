import sys
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from yt_dlp import YoutubeDL


FFMPEG_LOCATION = (
    Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)


QSS_STYLE = """
QMainWindow, QWidget#centralWidget {
    background-color: #121212;
}
QLabel {
    color: #E0E0E0;
    font-family: 'Arial';
}
QLabel#titleLabel {
    color: #FFFFFF;
    font-size: 24px;
    font-weight: bold;
}
QLabel#subtitleLabel, QLabel#statusLabel {
    color: #A0A0A0;
    font-size: 12px;
}
QProgressBar {
    background-color: #1E1E1E;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #7B2CBF;
    border-radius: 5px;
}
QLineEdit {
    background-color: #1E1E1E;
    border: 2px solid #333333;
    border-radius: 10px;
    padding: 10px;
    color: #FFFFFF;
    font-size: 13px;
}
QLineEdit:focus {
    border: 2px solid #7B2CBF;
}
QLineEdit#pathEntry {
    color: #A0A0A0;
}
QLineEdit#pathEntry:focus {
    border: 2px solid #333333;
}
QPushButton {
    background-color: #7B2CBF;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 11px 18px;
    font-weight: bold;
    font-size: 14px;
}
QPushButton:hover {
    background-color: #9D4EDD;
}
QPushButton:disabled {
    background-color: #444444;
    color: #888888;
}
QPushButton#stopButton {
    background-color: #3A1F2D;
    color: #FF5555;
}
QPushButton#stopButton:hover:!disabled {
    background-color: #51283B;
}
QPushButton#stopButton:disabled {
    background-color: #444444;
    color: #888888;
}
QListWidget {
    background-color: #1E1E1E;
    border: 1px solid #2D2D2D;
    border-radius: 10px;
    padding: 8px;
    outline: none;
}
QListWidget::item {
    border-radius: 8px;
    padding: 6px;
}
QListWidget::item:hover {
    background-color: #292132;
}
QListWidget::item:selected {
    background-color: #38234A;
}
QLabel#trackIcon {
    background-color: #7B2CBF;
    color: #FFFFFF;
    border-radius: 10px;
    font-size: 20px;
    font-weight: bold;
}
QFrame#separator {
    background-color: #2D2D2D;
    max-height: 1px;
}
"""


class DownloadThread(QThread):
    progress = Signal(str)
    progress_percent = Signal(int)
    downloaded = Signal(str, str, str)
    error = Signal(str)

    def __init__(self, url: str, output_dir: Path) -> None:
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.is_killed = False

    def stop(self) -> None:
        self.is_killed = True

    def _match_filter_hook(self, info_dict, *, incomplete):
        if self.is_killed:
            raise RuntimeError("Загрузка принудительно остановлена пользователем.")
        return None

    def run(self) -> None:
        try:
            options = {
                "format": "bestaudio/best",
                "outtmpl": str(self.output_dir / "%(title)s.%(ext)s"),
                "ffmpeg_location": str(FFMPEG_LOCATION),
                "noplaylist": False,
                "quiet": True,
                "no_warnings": True,
                "match_filter": self._match_filter_hook,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "prefer_ffmpeg": True,
                "progress_hooks": [self._on_progress],
            }
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(self.url, download=True)

            if not info:
                raise RuntimeError("yt-dlp не вернул информацию о треке.")

            entries = info.get("entries") or [info]
            downloaded_count = 0
            for entry in entries:
                if not entry:
                    continue
                requested_downloads = entry.get("requested_downloads") or []
                requested_path = (
                    requested_downloads[0].get("filepath")
                    if requested_downloads and requested_downloads[0]
                    else None
                )
                filepath = (
                    requested_path
                    or entry.get("_filename")
                    or downloader.prepare_filename(entry)
                )
                title = entry.get("title") or Path(filepath).stem
                thumbnail = entry.get("thumbnail") or ""
                self.downloaded.emit(title, filepath, thumbnail)
                downloaded_count += 1
            if downloaded_count == 0:
                raise RuntimeError("В плейлисте не найдено загруженных треков.")
        except BaseException as exc:
            if self.is_killed and str(exc) == "Stop":
                return
            if self.is_killed and str(exc) == "Загрузка принудительно остановлена пользователем.":
                return
            if isinstance(exc, Exception):
                self.error.emit(str(exc))
            else:
                raise

    def _on_progress(self, data: dict) -> None:
        if self.is_killed:
            raise BaseException("Stop")

        if data.get("status") == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = int(downloaded * 100 / total) if total > 0 else 0
            percent = max(0, min(100, percent))
            self.progress_percent.emit(percent)
            item_title = (data.get("info_dict") or {}).get("title")
            status = (
                f"Загрузка: {item_title} — {percent}%"
                if item_title
                else f"Загрузка: {percent}%"
            )
            self.progress.emit(status)
        elif data.get("status") == "finished":
            self.progress_percent.emit(100)
            self.progress.emit("Обработка загруженного трека…")


class MusicDownloaderWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Neon Music Downloader")
        self.resize(620, 560)
        self.setMinimumSize(480, 420)
        self._download_thread: DownloadThread | None = None
        self.network_manager = QNetworkAccessManager(self)
        self.output_dir = Path.home() / "Music" / "YouTube Downloads"
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Neon Music Downloader")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Вставьте ссылку на YouTube-видео для загрузки аудио")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url_entry.returnPressed.connect(self.start_download)
        layout.addWidget(self.url_entry)

        path_layout = QHBoxLayout()
        self.path_entry = QLineEdit()
        self.path_entry.setObjectName("pathEntry")
        self.path_entry.setReadOnly(True)
        self.path_entry.setText(str(self.output_dir))
        path_layout.addWidget(self.path_entry, 1)

        self.path_button = QPushButton("Обзор…")
        self.path_button.clicked.connect(self.choose_output_dir)
        path_layout.addWidget(self.path_button)
        layout.addLayout(path_layout)

        button_layout = QHBoxLayout()
        self.download_button = QPushButton("Скачать")
        self.download_button.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_button)

        self.stop_button = QPushButton("Стоп")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_download)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel(
            "Файлы сохраняются в папку Music/YouTube Downloads"
        )
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        list_heading = QLabel("Загруженные треки")
        list_heading.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(list_heading)

        self.track_list = QListWidget()
        self.track_list.setSpacing(4)
        self.track_list.itemActivated.connect(self.open_track)
        layout.addWidget(self.track_list, 1)

    def choose_output_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения",
            str(self.output_dir),
        )
        if dir_path:
            self.output_dir = Path(dir_path)
            self.path_entry.setText(dir_path)
            self.status_label.setText("Папка сохранения изменена")

    def start_download(self) -> None:
        url = self.url_entry.text().strip()
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            self.status_label.setText(
                "Введите корректную ссылку, начинающуюся с http:// или https://."
            )
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_button.setEnabled(False)
        self.url_entry.setEnabled(False)
        self.path_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Подключение к YouTube…")

        worker = DownloadThread(url, self.output_dir)
        worker.progress.connect(self.status_label.setText)
        worker.progress_percent.connect(self.progress_bar.setValue)
        worker.downloaded.connect(self.add_track)
        worker.error.connect(self.show_download_error)
        worker.finished.connect(self.on_download_finished)
        self._download_thread = worker
        worker.start()

    def stop_download(self) -> None:
        worker = self._download_thread
        if worker is not None and worker.isRunning():
            worker.stop()
            self.stop_button.setEnabled(False)
            self.status_label.setText("Статус: Остановка процесса... Ожидайте.")

    def add_track(self, title: str, filepath: str, thumbnail_url: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, filepath)

        row = QWidget()
        icon = QLabel("♪")
        icon.setObjectName("trackIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(44, 44)

        track_title = QLabel(title)
        track_title.setToolTip(filepath)
        track_title.setWordWrap(True)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(8, 6, 8, 6)
        content_layout.setSpacing(12)
        content_layout.addWidget(icon)
        content_layout.addWidget(track_title, 1)
        row.setLayout(content_layout)

        item.setSizeHint(row.sizeHint())
        self.track_list.addItem(item)
        self.track_list.setItemWidget(item, row)
        self.track_list.scrollToItem(item)
        self.status_label.setText(f"Загружен трек: {title}")
        if thumbnail_url:
            request = QNetworkRequest(QUrl(thumbnail_url))
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            reply = self.network_manager.get(request)
            reply.finished.connect(
                lambda current_reply=reply, target_icon=icon:
                self._on_thumbnail_loaded(current_reply, target_icon)
            )

    def _on_thumbnail_loaded(
        self,
        reply: QNetworkReply,
        icon: QLabel,
    ) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll().data()):
                icon.setText("")
                icon.setPixmap(self._rounded_thumbnail(pixmap))
        reply.deleteLater()

    @staticmethod
    def _rounded_thumbnail(pixmap: QPixmap) -> QPixmap:
        scaled = pixmap.scaled(
            44,
            44,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_offset = (scaled.width() - 44) // 2
        y_offset = (scaled.height() - 44) // 2
        cropped = scaled.copy(x_offset, y_offset, 44, 44)

        rounded = QPixmap(44, 44)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, 44, 44, 10, 10)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        return rounded

    def open_track(self, item: QListWidgetItem) -> None:
        filepath = item.data(Qt.ItemDataRole.UserRole)
        if filepath and not QDesktopServices.openUrl(QUrl.fromLocalFile(filepath)):
            self.status_label.setText("Не удалось открыть файл трека.")

    def show_download_error(self, message: str) -> None:
        self.status_label.setText("Не удалось загрузить трек.")
        QMessageBox.critical(self, "Ошибка загрузки", message)

    def on_download_finished(self) -> None:
        self.url_entry.clear()
        self.url_entry.setEnabled(True)
        self.path_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self._download_thread = None

    def closeEvent(self, event) -> None:
        if self._download_thread and self._download_thread.isRunning():
            self.status_label.setText("Дождитесь завершения загрузки перед закрытием окна.")
            event.ignore()
            return
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS_STYLE)
    window = MusicDownloaderWindow()
    window.show()        
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
