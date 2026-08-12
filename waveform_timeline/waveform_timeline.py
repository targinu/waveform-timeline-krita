"""Waveform Timeline - Krita Python plugin.

Docker separado que decodifica o audio do documento (via ffmpeg),
desenha a waveform alinhada ao eixo de frames da animacao e sincroniza
um playhead com o currentTime do documento. Clicar na waveform pula
para o frame correspondente.
"""

import os
import shutil
import subprocess
import sys
import time
from array import array

try:  # Krita 5.2+ pode rodar em PyQt6 ou PyQt5
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableView,
        QSpinBox)
    from PyQt6.QtGui import QPainter, QColor, QPen
    from PyQt6.QtCore import Qt, QTimer, QPointF, QEvent
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _PAINT_EVENT_TYPE = QEvent.Type.Paint
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableView,
        QSpinBox)
    from PyQt5.QtGui import QPainter, QColor, QPen
    from PyQt5.QtCore import Qt, QTimer, QPointF, QEvent
    _ALIGN_CENTER = Qt.AlignCenter
    _PAINT_EVENT_TYPE = QEvent.Paint

from krita import (
    DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita)


# ffmpeg/ffplay do sistema; se o Krita usar um bundle proprio, aponte aqui.
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPLAY = shutil.which("ffplay") or "ffplay"
DECODE_SR = 8000          # taxa usada so para gerar o envelope visual
ENVELOPE_BUCKETS = 4000   # resolucao do envelope min/max em cache
SCRUB_DURATION = 0.15     # duracao (s) de cada trecho tocado ao arrastar
SCRUB_MIN_INTERVAL = 0.09  # intervalo minimo (s) entre disparos de preview

# Evita a janela de console piscando no Windows a cada chamada de ffmpeg/ffplay.
_POPEN_KWARGS = {}
if sys.platform.startswith("win"):
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def find_audio_path(doc):
    """Retorna o caminho do primeiro track de audio do documento, ou None."""
    if doc is None:
        return None
    getter = getattr(doc, "audioTracks", None)
    if callable(getter):
        try:
            tracks = getter()
            if tracks:
                path = tracks[0]
                if path and os.path.isfile(path):
                    return path
        except Exception:
            return None
    return None


_DEBUG_LOG = os.path.join(
    os.environ.get("TEMP", "."), "waveform_timeline_debug.log")


def _log_debug(msg):
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def decode_envelope(path):
    """Decodifica o audio para PCM mono via ffmpeg e monta o envelope.

    Retorna (envelope, duracao_em_segundos). envelope e uma lista de
    pares (min, max) normalizados em [-1, 1]. Em falha retorna (None, 0.0).
    """
    # Le o arquivo em Python e envia os bytes via stdin: passar o caminho
    # como argumento de linha de comando quebra com acentos em alguns
    # builds de ffmpeg no Windows (o argv chega com a codificacao errada).
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        _log_debug("Falha ao ler arquivo de audio: %r" % exc)
        return None, 0.0

    cmd = [
        FFMPEG, "-v", "error", "-i", "-",
        "-ac", "1", "-ar", str(DECODE_SR),
        "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, input=data, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, **_POPEN_KWARGS)
    except Exception as exc:
        stderr = getattr(exc, "stderr", None)
        _log_debug("Falha ao rodar ffmpeg: %r | stderr=%r" % (
            exc, stderr.decode("utf-8", "replace") if stderr else None))
        return None, 0.0
    if proc.stderr:
        _log_debug("ffmpeg stderr: %s" % proc.stderr.decode("utf-8", "replace"))

    samples = array("h")
    samples.frombytes(proc.stdout)
    total = len(samples)
    if total == 0:
        return None, 0.0

    duration = total / float(DECODE_SR)
    buckets = min(ENVELOPE_BUCKETS, total)
    step = total / float(buckets)
    scale = 1.0 / 32768.0

    envelope = []
    pos = 0.0
    for _ in range(buckets):
        start = int(pos)
        end = int(pos + step)
        if end <= start:
            end = start + 1
        chunk = samples[start:end]
        envelope.append((min(chunk) * scale, max(chunk) * scale))
        pos += step

    return envelope, duration


class WaveformView(QWidget):
    """Widget que pinta a waveform e o playhead sobre um eixo de frames."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self._envelope = None
        self._audio_frames = 0     # duracao do audio expressa em frames
        self._total_frames = 1     # largura do eixo desenhado (modo standalone)
        self._current_frame = 0
        self._doc = None

        # Quando a Linha do Tempo da Animacao nativa e encontrada, o eixo
        # passa a usar o mesmo pixel-por-frame (zoom) e offset (scroll)
        # dela, alinhando as colunas como se fosse uma trilha de audio.
        self._tl_offset = 0
        self._tl_section_size = None
        self._tl_left_inset = 0

        # Callbacks preenchidos pelo WaveformDocker: tocar/parar um trecho
        # de audio enquanto o usuario arrasta o mouse sobre a waveform.
        self._dragging = False
        self.on_scrub = None
        self.on_scrub_end = None

    def set_document(self, doc):
        self._doc = doc

    def set_data(self, envelope, audio_frames, total_frames):
        self._envelope = envelope
        self._audio_frames = max(0, audio_frames)
        self._total_frames = max(1, total_frames)
        self.update()

    def set_current_frame(self, frame):
        if frame != self._current_frame:
            self._current_frame = frame
            self.update()

    def set_timeline_scroll(self, offset, section_size, left_inset):
        if (offset, section_size, left_inset) != (
                self._tl_offset, self._tl_section_size, self._tl_left_inset):
            self._tl_offset = offset
            self._tl_section_size = section_size
            self._tl_left_inset = left_inset
            self.update()

    def _frame_to_x(self, frame):
        if self._tl_section_size:
            return self._tl_left_inset + frame * self._tl_section_size - self._tl_offset
        return (frame / float(self._total_frames)) * self.width()

    def _x_to_frame(self, x):
        if self._tl_section_size:
            return int((x - self._tl_left_inset + self._tl_offset) / float(self._tl_section_size))
        return int((x / float(max(1, self.width()))) * self._total_frames)

    def _seek_to_x(self, x):
        frame = max(0, min(self._x_to_frame(x), self._total_frames - 1))
        self._doc.setCurrentTime(frame)
        self.set_current_frame(frame)
        if self.on_scrub:
            self.on_scrub(frame)

    def mousePressEvent(self, event):
        if self._doc is None:
            return
        x = event.position().x() if hasattr(event, "position") else event.x()
        if x < self._tl_left_inset:
            return  # area equivalente a coluna de nomes de camada, ignora clique
        self._dragging = True
        self._seek_to_x(x)

    def mouseMoveEvent(self, event):
        if not self._dragging or self._doc is None:
            return
        x = event.position().x() if hasattr(event, "position") else event.x()
        self._seek_to_x(x)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        if self.on_scrub_end:
            self.on_scrub_end()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 30, 30))
        w = self.width()
        h = self.height()
        mid = h / 2.0

        if self._envelope and self._audio_frames > 0:
            n = len(self._envelope)
            p.setPen(QPen(QColor(90, 170, 255), 1))
            for x in range(int(self._tl_left_inset), w):
                frame = self._x_to_frame(x)
                if frame < 0 or frame >= self._audio_frames:
                    continue
                idx = min(int((frame / float(self._audio_frames)) * n), n - 1)
                lo, hi = self._envelope[idx]
                y_top = mid - hi * (mid - 2)
                y_bot = mid - lo * (mid - 2)
                p.drawLine(QPointF(x, y_top), QPointF(x, y_bot))
        else:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), _ALIGN_CENTER, "Sem audio no documento")

        px = self._frame_to_x(self._current_frame)
        p.setPen(QPen(QColor(255, 80, 80), 2))
        p.drawLine(QPointF(px, 0), QPointF(px, h))
        p.end()


class WaveformDocker(DockWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Waveform Timeline")

        self._doc = None
        self._cache = {}  # (path, mtime) -> (envelope, duracao)
        self._timeline_table = None  # QTableView da Linha do Tempo nativa
        self._audio_path = None
        self._scrub_proc = None
        self._last_scrub_time = 0.0

        # Estimativa do frame durante o Play nativo: confirmado
        # empiricamente que TUDO que da pra ler via scripting nesses
        # widgets (currentTime(), currentIndex() da tabela, offset/zoom
        # do cabecalho, ate o estado do botao Play/Pause) fica congelado
        # durante a reproducao nativa - so o repaint visual continua. A
        # unica pista real e a frequencia desses repaints: durante o Play
        # eles chegam em rajada rapida (a cada frame); parados ou ociosos,
        # sao esporadicos. Usamos isso como sinal de "esta tocando".
        self._play_started_at = None
        self._play_started_frame = 0
        self._last_viewport_paint_at = 0.0
        self._viewport_paint_gap = 999.0
        self._speed_spinbox = None  # QSpinBox "Velocidade" (25-200%)
        self._last_speed = None
        # fps nominal do documento nem sempre bate com a velocidade real
        # de reproducao alcancada (renderizacao pode ser mais lenta). A
        # gente calibra medindo o avanco real entre o inicio do Play e a
        # proxima pausa, e usa essa taxa medida daí em diante.
        self._measured_fps = None

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self._label = QLabel("Nenhum documento")
        reload_btn = QPushButton("Recarregar")
        reload_btn.clicked.connect(self._reload_audio)
        bar.addWidget(self._label, 1)
        bar.addWidget(reload_btn, 0)
        layout.addLayout(bar)

        self._view = WaveformView(root)
        self._view.on_scrub = self._on_scrub
        self._view.on_scrub_end = self._stop_scrub
        layout.addWidget(self._view, 1)
        self.setWidget(root)

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 fps para o playhead
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _find_timeline_table(self):
        """Localiza o QTableView interno da Linha do Tempo da Animacao
        nativa, pra ler seu offset/zoom (ver TimelineDocker no Krita).
        Fica em cache; se o objeto for destruido, procura de novo."""
        if self._timeline_table is not None:
            try:
                self._timeline_table.objectName()
                return self._timeline_table
            except RuntimeError:
                self._timeline_table = None
        try:
            dockers = Krita.instance().dockers()
        except Exception:
            return None
        for d in dockers:
            if d.objectName() == "TimelineDocker":
                tables = d.findChildren(QTableView)
                if tables:
                    self._timeline_table = tables[0]
                    # O QTimer nao dispara durante a reproducao nativa (o
                    # loop de playback do Krita nao cede vez pros timers
                    # Python), mas algo nesses widgets deve se repintar a
                    # cada frame do Play - a gente tenta pegar carona nisso
                    # via event filter em varios pontos da arvore.
                    watch = [d, self._timeline_table,
                             self._timeline_table.viewport(),
                             self._timeline_table.horizontalHeader()]
                    for w in watch:
                        w.installEventFilter(self)
                break
        return self._timeline_table

    def eventFilter(self, obj, event):
        if event.type() == _PAINT_EVENT_TYPE:
            if self._timeline_table is not None and obj is self._timeline_table.viewport():
                now = time.monotonic()
                self._viewport_paint_gap = now - self._last_viewport_paint_at
                self._last_viewport_paint_at = now
            self._sync_from_timeline()
        return super().eventFilter(obj, event)

    def _is_playing(self):
        now = time.monotonic()
        recent = (now - self._last_viewport_paint_at) < 0.4
        fast = 0 < self._viewport_paint_gap < 0.4
        return recent and fast

    def _find_speed_spinbox(self):
        """Localiza o QSpinBox "Velocidade" (25%-200%) da Linha do Tempo
        nativa - a estimativa de frame durante o Play precisa multiplicar
        o fps por essa velocidade, senao desanda quando ela nao e 100%."""
        if self._speed_spinbox is not None:
            try:
                self._speed_spinbox.value()
                return self._speed_spinbox
            except RuntimeError:
                self._speed_spinbox = None
        table = self._find_timeline_table()
        if table is None:
            return None
        docker = table.parent()
        while docker is not None and docker.objectName() != "TimelineDocker":
            docker = docker.parent()
        if docker is None:
            return None
        for sb in docker.findChildren(QSpinBox):
            if sb.minimum() == 25 and sb.maximum() == 200:
                self._speed_spinbox = sb
                break
        return self._speed_spinbox

    def _get_playback_speed(self):
        sb = self._find_speed_spinbox()
        if sb is None:
            return 1.0
        try:
            return max(1, sb.value()) / 100.0
        except Exception:
            return 1.0

    def _calibrate_fps(self):
        """Mede a taxa real de avanco de frames do ultimo trecho de Play
        comparando com o doc.currentTime() real no momento da pausa, e
        usa isso pra corrigir futuras estimativas - o fps nominal do
        documento nem sempre bate com a velocidade real de reproducao
        alcancada pela renderizacao."""
        if self._play_started_at is None:
            return
        elapsed = time.monotonic() - self._play_started_at
        if elapsed < 0.5:
            return
        advance = self._doc.currentTime() - self._play_started_frame
        if advance <= 0:
            return  # deu loop no meio do trecho ou nao avancou; nao calibra
        speed = self._last_speed or 1.0
        measured = (advance / elapsed) / speed
        if measured <= 0:
            return
        self._measured_fps = (
            measured if self._measured_fps is None
            else 0.5 * self._measured_fps + 0.5 * measured)

    def _update_current_frame(self):
        if self._doc is None:
            return
        if not self._is_playing():
            self._calibrate_fps()
            self._play_started_at = None
            self._last_speed = None
            self._view.set_current_frame(self._doc.currentTime())
            return

        now = time.monotonic()
        speed = self._get_playback_speed()
        fps = self._measured_fps or (self._doc.framesPerSecond() or 24)
        if self._play_started_at is None:
            self._play_started_at = now
            self._play_started_frame = self._doc.currentTime()
        elif speed != self._last_speed:
            # Reancora no frame estimado ate agora antes de trocar de
            # velocidade, pra nao dar salto na hora da mudanca.
            self._play_started_frame += int(
                (now - self._play_started_at) * fps * self._last_speed)
            self._play_started_at = now
        self._last_speed = speed

        frame = self._play_started_frame + int((now - self._play_started_at) * fps * speed)
        try:
            start = self._doc.playbackStartTime()
            end = self._doc.playBackEndTime()
            if end > start:
                frame = start + (frame - start) % (end - start + 1)
        except Exception:
            pass
        self._view.set_current_frame(frame)

    def _sync_from_timeline(self):
        self._update_current_frame()
        self._sync_timeline_scroll()

    def _sync_timeline_scroll(self):
        table = self._find_timeline_table()
        if table is None:
            return
        header = table.horizontalHeader()
        section_size = (
            header.sectionSize(0) if header.count() > 0
            else header.defaultSectionSize())
        self._view.set_timeline_scroll(
            header.offset(), section_size, table.verticalHeader().width())

    # hook chamado pelo Krita quando o canvas ativo muda
    def canvasChanged(self, canvas):
        self._sync_document()

    def _sync_document(self):
        doc = Krita.instance().activeDocument()
        if doc is not self._doc:
            self._doc = doc
            self._view.set_document(doc)
            self._reload_audio()

    def _on_scrub(self, frame):
        """Toca um trecho curto do audio ao redor do frame, chamado pela
        WaveformView enquanto o usuario arrasta o mouse sobre ela."""
        if not self._audio_path or self._doc is None:
            return
        now = time.monotonic()
        if now - self._last_scrub_time < SCRUB_MIN_INTERVAL:
            return
        self._last_scrub_time = now
        fps = self._doc.framesPerSecond() or 24
        start = max(0.0, frame / float(fps) - SCRUB_DURATION / 2.0)
        self._stop_scrub()
        cmd = [
            FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet",
            "-ss", "%.3f" % start, "-t", str(SCRUB_DURATION),
            self._audio_path,
        ]
        try:
            self._scrub_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **_POPEN_KWARGS)
        except OSError as exc:
            _log_debug("Falha ao iniciar ffplay: %r" % exc)
            self._scrub_proc = None

    def _stop_scrub(self):
        if self._scrub_proc is not None and self._scrub_proc.poll() is None:
            try:
                self._scrub_proc.terminate()
            except Exception:
                pass
        self._scrub_proc = None

    def _reload_audio(self):
        doc = self._doc
        path = find_audio_path(doc)
        self._audio_path = path

        if not path:
            self._label.setText("Nenhum audio no documento")
            self._view.set_data(None, 0, doc.animationLength() if doc else 1)
            return

        key = (path, os.path.getmtime(path))
        if key in self._cache:
            envelope, duration = self._cache[key]
        else:
            self._label.setText("Decodificando audio...")
            envelope, duration = decode_envelope(path)
            self._cache[key] = (envelope, duration)

        fps = doc.framesPerSecond() or 24
        audio_frames = int(round(duration * fps))
        total_frames = max(doc.animationLength(), audio_frames, 1)
        self._view.set_data(envelope, audio_frames, total_frames)

        if envelope is None:
            self._label.setText("Falha ao decodificar (verifique o ffmpeg)")
        else:
            self._label.setText(
                "%s  |  %.2fs @ %dfps"
                % (os.path.basename(path), duration, fps))

    def _tick(self):
        doc = Krita.instance().activeDocument()
        if doc is not self._doc:
            self._sync_document()
            return
        self._sync_from_timeline()


Krita.instance().addDockWidgetFactory(
    DockWidgetFactory(
        "waveformTimeline",
        DockWidgetFactoryBase.DockBottom,
        WaveformDocker))
