import sys
import os
import shutil
import socket
import struct
import uuid
from PyQt6 import QtWidgets, QtCore, QtGui


class ImageWidget(QtWidgets.QWidget):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setMinimumSize(1280, 800)
		self._pixmap = None
		self._display_pixmap = None
		self._show_scaled = False
		self._scale_factor = 1.0
		self._zoom_step = 1.15
		self._min_scale_factor = 0.05
		self._max_scale_factor = 80.0
		self._annotations = []
		self._peak_markers = []
		self._show_grid = False
		self._show_values = False

	def set_image(self, image):
		'''
		image can be either QPixmap, QImage, np.ndarray, or a file path to an image. 
		You can implement the logic to convert these formats to a QPixmap and then 
		call self.update() to trigger a repaint of the widget.
		'''
		pixmap = None

		if isinstance(image, QtGui.QPixmap):
			pixmap = image
		elif isinstance(image, QtGui.QImage):
			pixmap = QtGui.QPixmap.fromImage(image)
		elif isinstance(image, (str, bytes)):
			if isinstance(image, bytes):
				image = image.decode("utf-8")
			pixmap = QtGui.QPixmap(image)
		else:
			# Lazy-import numpy support so it remains optional.
			try:
				import numpy as np
			except Exception:
				np = None

			if np is not None and isinstance(image, np.ndarray):
				array = image
				if not array.flags["C_CONTIGUOUS"]:
					array = np.ascontiguousarray(array)

				if array.ndim == 2:
					h, w = array.shape
					qimage = QtGui.QImage(
						array.data,
						w,
						h,
						array.strides[0],
						QtGui.QImage.Format.Format_Grayscale8,
					).copy()
					pixmap = QtGui.QPixmap.fromImage(qimage)
				elif array.ndim == 3 and array.shape[2] in (3, 4):
					h, w, ch = array.shape
					if ch == 3:
						qimage = QtGui.QImage(
							array.data,
							w,
							h,
							array.strides[0],
							QtGui.QImage.Format.Format_RGB888,
						).copy()
					else:
						qimage = QtGui.QImage(
							array.data,
							w,
							h,
							array.strides[0],
							QtGui.QImage.Format.Format_RGBA8888,
						).copy()
					pixmap = QtGui.QPixmap.fromImage(qimage)

		if pixmap is None or pixmap.isNull():
			raise ValueError("Unsupported image input or failed to load image")

		self._pixmap = pixmap
		self._rebuild_display_pixmap()
		self._sync_widget_size()
		self.updateGeometry()
		self.update()

	def set_show_scaled(self, enabled):
		self._show_scaled = bool(enabled)
		self._rebuild_display_pixmap()
		self._sync_widget_size()
		self.updateGeometry()
		self.update()

	def set_scale_factor(self, factor):
		factor = float(factor)
		if factor <= 0:
			raise ValueError("scale factor must be > 0")
		self._scale_factor = factor
		self._rebuild_display_pixmap()
		self._sync_widget_size()
		self.updateGeometry()
		self.update()

	def set_annotations(self, annotations):
		# Annotation coordinates are expected in original-image space.
		self._annotations = annotations or []
		self.update()

	def image_pixmap(self):
		return self._pixmap

	def set_show_grid(self, enabled):
		self._show_grid = bool(enabled)
		self.update()

	def set_show_values(self, enabled):
		self._show_values = bool(enabled)
		self.update()

	def add_peak_marker(self, x, y):
		self._peak_markers.append((float(x), float(y)))
		self.update()

	def clear_peak_markers(self):
		self._peak_markers.clear()
		self.update()

	def set_peak_markers(self, markers):
		self._peak_markers = [(float(x), float(y)) for x, y in markers]
		self.update()

	def is_zoomed(self):
		return self._show_scaled and abs(self._scale_factor - 1.0) > 1e-9

	def zoom_at(self, widget_pos, delta_y):
		if self._pixmap is None or self._display_pixmap is None or delta_y == 0:
			return None

		old_sx = self._display_pixmap.width() / self._pixmap.width()
		old_sy = self._display_pixmap.height() / self._pixmap.height()
		src_x = widget_pos.x() / old_sx
		src_y = widget_pos.y() / old_sy
		src_x = max(0.0, min(float(self._pixmap.width()), src_x))
		src_y = max(0.0, min(float(self._pixmap.height()), src_y))

		steps = delta_y / 120.0
		self._show_scaled = True
		new_factor = self._scale_factor * (self._zoom_step ** steps)
		new_factor = max(self._min_scale_factor, min(self._max_scale_factor, new_factor))

		if new_factor != self._scale_factor:
			self._scale_factor = new_factor
			self._rebuild_display_pixmap()
			self._sync_widget_size()
			self.updateGeometry()
			self.update()

		new_sx = self._display_pixmap.width() / self._pixmap.width()
		new_sy = self._display_pixmap.height() / self._pixmap.height()
		return QtCore.QPointF(src_x * new_sx, src_y * new_sy)

	def _rebuild_display_pixmap(self):
		if self._pixmap is None:
			self._display_pixmap = None
			return

		if self._show_scaled:
			target_w = max(1, int(self._pixmap.width() * self._scale_factor))
			target_h = max(1, int(self._pixmap.height() * self._scale_factor))
			self._display_pixmap = self._pixmap.scaled(
				target_w,
				target_h,
				QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
				QtCore.Qt.TransformationMode.FastTransformation,
			)
		else:
			self._display_pixmap = self._pixmap

	def _sync_widget_size(self):
		if self._display_pixmap is None:
			self.setMinimumSize(1280, 800)
			self.setMaximumSize(QtWidgets.QWIDGETSIZE_MAX, QtWidgets.QWIDGETSIZE_MAX)
			self.resize(1280, 800)
			return

		size = self._display_pixmap.size()
		self.setMinimumSize(size)
		self.setMaximumSize(size)
		self.resize(size)

	def sizeHint(self):
		if self._display_pixmap is None:
			return QtCore.QSize(1280, 800)
		return self._display_pixmap.size()


	def paintEvent(self, event):
		painter = QtGui.QPainter(self)
		painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.white)

		if self._display_pixmap is None:
			return

		if self._pixmap.width() > 0 and self._pixmap.height() > 0:
			sx = self._display_pixmap.width() / self._pixmap.width()
			sy = self._display_pixmap.height() / self._pixmap.height()
		else:
			sx = sy = 1.0

		src_w = self._pixmap.width()
		src_h = self._pixmap.height()
		draw_grid = self._show_grid and min(sx, sy) > 4.0
		draw_values = self._show_values and min(sx, sy) > 20.0

		if draw_grid:
			# Draw the source pixmap through the painter's own scale transform, then draw
			# grid lines in source-pixel coordinates using the same transform. This guarantees
			# the lines land exactly on pixel boundaries regardless of Qt's internal rounding.
			painter.save()
			painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
			painter.setTransform(QtGui.QTransform.fromScale(sx, sy))
			painter.drawPixmap(0, 0, self._pixmap)

			grid_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 80))
			grid_pen.setCosmetic(True)
			painter.setPen(grid_pen)
			for i in range(1, src_w):
				painter.drawLine(QtCore.QLineF(i, 0, i, src_h))
			for j in range(1, src_h):
				painter.drawLine(QtCore.QLineF(0, j, src_w, j))
			painter.restore()
		else:
			painter.drawPixmap(0, 0, self._display_pixmap)

		if draw_values:
			image = self._pixmap.toImage().convertToFormat(
				QtGui.QImage.Format.Format_RGB32
			)
			font = QtGui.QFont()
			font.setPixelSize(max(8, min(14, int(min(sx, sy) * 0.4))))
			painter.setFont(font)

			clip = event.rect()
			px0 = max(0, int(clip.x() / sx))
			px1 = min(src_w, int(clip.right() / sx) + 2)
			py0 = max(0, int(clip.y() / sy))
			py1 = min(src_h, int(clip.bottom() / sy) + 2)

			for py in range(py0, py1):
				for px in range(px0, px1):
					qc = QtGui.QColor(image.pixel(px, py))
					val = (qc.red() + qc.green() + qc.blue()) // 3
					text_color = (
						QtCore.Qt.GlobalColor.black
						if val >= 128
						else QtCore.Qt.GlobalColor.white
					)
					painter.setPen(QtGui.QPen(text_color))
					painter.drawText(
						QtCore.QRectF(px * sx, py * sy, sx, sy),
						QtCore.Qt.AlignmentFlag.AlignCenter,
						str(val),
					)

		for annotation in self._annotations:
			kind = annotation.get("kind")
			color = QtGui.QColor(annotation.get("color", "red"))
			width = max(1.0, float(annotation.get("width", 2.0)))
			pen = QtGui.QPen(color, width)
			painter.setPen(pen)

			if kind == "line":
				x1, y1, x2, y2 = annotation["points"]
				painter.drawLine(
					int(x1 * sx),
					int(y1 * sy),
					int(x2 * sx),
					int(y2 * sy),
				)
			elif kind == "rect":
				x, y, w, h = annotation["rect"]
				painter.drawRect(
					int(x * sx),
					int(y * sy),
					int(w * sx),
					int(h * sy),
				)
			elif kind == "ellipse":
				x, y, w, h = annotation["rect"]
				painter.drawEllipse(
					int(x * sx),
					int(y * sy),
					int(w * sx),
					int(h * sy),
				)

		if self._peak_markers:
			pen = QtGui.QPen(QtGui.QColor(255, 50, 50), 1.5)
			painter.setPen(pen)
			painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
			r = 5.0
			for mx, my in self._peak_markers:
				cx, cy = (mx + 0.5) * sx, (my + 0.5) * sy
				painter.drawEllipse(QtCore.QRectF(cx - r, cy - r, r * 2.0, r * 2.0))

	def wheelEvent(self, event):
		if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
			self.zoom_at(event.position(), event.angleDelta().y())
			event.accept()
			return

		super().wheelEvent(event)


# ---------------------------------------------------------------------------
# Helpers used by FeatureDetectionDialog
# ---------------------------------------------------------------------------

def _hline():
	w = QtWidgets.QFrame()
	w.setFrameShape(QtWidgets.QFrame.Shape.HLine)
	w.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
	return w


def _form_page():
	w = QtWidgets.QWidget()
	f = QtWidgets.QFormLayout(w)
	f.setContentsMargins(0, 4, 0, 4)
	return w, f


def _spinbox(form, label, lo, hi, default, tip=""):
	sb = QtWidgets.QSpinBox()
	sb.setRange(lo, hi)
	sb.setValue(default)
	if tip:
		sb.setToolTip(tip)
	form.addRow(label, sb)
	return sb


def _dspinbox(form, label, lo, hi, default, step=0.1, decimals=2, tip=""):
	sb = QtWidgets.QDoubleSpinBox()
	sb.setRange(lo, hi)
	sb.setSingleStep(step)
	sb.setDecimals(decimals)
	sb.setValue(default)
	if tip:
		sb.setToolTip(tip)
	form.addRow(label, sb)
	return sb


def _checkbox(form, label, default):
	cb = QtWidgets.QCheckBox()
	cb.setChecked(default)
	form.addRow(label, cb)
	return cb


# ---------------------------------------------------------------------------
# Feature detection dialog
# ---------------------------------------------------------------------------

class FeatureDetectionDialog(QtWidgets.QDialog):
	detected = QtCore.pyqtSignal(list)   # emits list of (float x, float y)

	_METHODS = ["FAST", "GFTT", "SIFT", "ORB", "BRISK", "AKAZE"]

	def __init__(self, pixmap, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Feature Detection")
		self.setMinimumWidth(340)
		self._pixmap = pixmap
		self._setup_ui()

	# --- UI construction ---

	def _setup_ui(self):
		outer = QtWidgets.QVBoxLayout(self)

		form = QtWidgets.QFormLayout()
		self._method_box = QtWidgets.QComboBox()
		self._method_box.addItems(self._METHODS)
		form.addRow("Method:", self._method_box)
		outer.addLayout(form)

		outer.addWidget(_hline())

		self._stack = QtWidgets.QStackedWidget()
		for builder in (
			self._make_fast_page,
			self._make_gftt_page,
			self._make_sift_page,
			self._make_orb_page,
			self._make_brisk_page,
			self._make_akaze_page,
		):
			self._stack.addWidget(builder())
		self._method_box.currentIndexChanged.connect(self._stack.setCurrentIndex)
		outer.addWidget(self._stack)

		outer.addWidget(_hline())

		row = QtWidgets.QHBoxLayout()
		detect_btn = QtWidgets.QPushButton("Detect")
		detect_btn.setDefault(True)
		detect_btn.clicked.connect(self._on_detect)
		row.addWidget(detect_btn)
		self._status = QtWidgets.QLabel("")
		row.addWidget(self._status)
		row.addStretch()
		close_btn = QtWidgets.QPushButton("Close")
		close_btn.clicked.connect(self.close)
		row.addWidget(close_btn)
		outer.addLayout(row)

	def _make_fast_page(self):
		w, f = _form_page()
		self._fast_threshold = _spinbox(f, "Threshold:", 1, 255, 10)
		self._fast_nms       = _checkbox(f, "Non-max suppression:", True)
		return w

	def _make_gftt_page(self):
		w, f = _form_page()
		self._gftt_max      = _spinbox( f, "Max corners:",   1, 100000, 1000)
		self._gftt_quality  = _dspinbox(f, "Quality level:", 0.001, 1.0, 0.01, step=0.005, decimals=3)
		self._gftt_min_dist = _dspinbox(f, "Min distance:",  1.0, 500.0, 10.0)
		self._gftt_harris   = _checkbox(f, "Use Harris detector:", False)
		return w

	def _make_sift_page(self):
		w, f = _form_page()
		self._sift_features = _spinbox( f, "Max features (0=∞):", 0, 100000, 500)
		self._sift_contrast = _dspinbox(f, "Contrast threshold:", 0.001, 0.5, 0.04, step=0.005, decimals=3)
		self._sift_edge     = _spinbox( f, "Edge threshold:",     1, 100, 10)
		return w

	def _make_orb_page(self):
		w, f = _form_page()
		self._orb_features = _spinbox( f, "Max features:",   1, 100000, 500)
		self._orb_scale    = _dspinbox(f, "Scale factor:",   1.05, 2.0, 1.2, step=0.05)
		self._orb_levels   = _spinbox( f, "Pyramid levels:", 1, 16, 8)
		return w

	def _make_brisk_page(self):
		w, f = _form_page()
		self._brisk_thresh  = _spinbox(f, "Threshold:", 1, 255, 30)
		self._brisk_octaves = _spinbox(f, "Octaves:",   0, 8,   3)
		return w

	def _make_akaze_page(self):
		w, f = _form_page()
		self._akaze_threshold = _dspinbox(f, "Threshold:", 0.0001, 0.1, 0.001, step=0.0001, decimals=4)
		self._akaze_octaves   = _spinbox( f, "Octaves:",        1, 8, 4)
		self._akaze_layers    = _spinbox( f, "Octave layers:",  1, 8, 4)
		return w

	# --- Detection ---

	def _on_detect(self):
		try:
			import cv2
			import numpy as np
		except ImportError:
			QtWidgets.QMessageBox.critical(
				self, "Missing dependency",
				"OpenCV (cv2) and NumPy are required.\n"
				"Install with:  pip install opencv-python numpy",
			)
			return

		img = self._pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
		h, w = img.height(), img.width()
		ptr = img.bits()
		ptr.setsize(h * img.bytesPerLine())
		arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine())[: , :w * 4].reshape(h, w, 4)
		gray = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)

		method = self._METHODS[self._method_box.currentIndex()]
		try:
			kps = self._run_detector(cv2, gray, method)
		except Exception as exc:
			QtWidgets.QMessageBox.warning(self, "Detection error", str(exc))
			return

		self._status.setText(f"{len(kps)} keypoint(s)")
		self.detected.emit([(kp.pt[0], kp.pt[1]) for kp in kps])

	def _run_detector(self, cv2, gray, method):
		if method == "GFTT":
			corners = cv2.goodFeaturesToTrack(
				gray,
				maxCorners=self._gftt_max.value(),
				qualityLevel=self._gftt_quality.value(),
				minDistance=self._gftt_min_dist.value(),
				useHarrisDetector=self._gftt_harris.isChecked(),
			)
			if corners is None:
				return []
			return [cv2.KeyPoint(float(c[0][0]), float(c[0][1]), 1.0) for c in corners]

		if method == "FAST":
			det = cv2.FastFeatureDetector_create(
				threshold=self._fast_threshold.value(),
				nonmaxSuppression=self._fast_nms.isChecked(),
			)
		elif method == "SIFT":
			det = cv2.SIFT_create(
				nfeatures=self._sift_features.value(),
				contrastThreshold=self._sift_contrast.value(),
				edgeThreshold=self._sift_edge.value(),
			)
		elif method == "ORB":
			det = cv2.ORB_create(
				nfeatures=self._orb_features.value(),
				scaleFactor=self._orb_scale.value(),
				nlevels=self._orb_levels.value(),
			)
		elif method == "BRISK":
			det = cv2.BRISK_create(
				thresh=self._brisk_thresh.value(),
				octaves=self._brisk_octaves.value(),
			)
		elif method == "AKAZE":
			det = cv2.AKAZE_create(
				threshold=self._akaze_threshold.value(),
				nOctaves=self._akaze_octaves.value(),
				nOctaveLayers=self._akaze_layers.value(),
			)
		else:
			return []
		return det.detect(gray, None)


class ImageReceiver(QtCore.QThread):
	"""Listens on TCP 0.0.0.0:14972 for raw image frames.

	Protocol
	--------
	Each image is prefixed by a 16-byte header (all fields little-endian):

	    Offset  Size  Type    Description
	    ──────  ────  ──────  ────────────────────────────────────────
	         0     4  bytes   Magic: b'WIMG'
	         4     4  uint32  Width  (pixels)
	         8     4  uint32  Height (pixels)
	        12     4  uint32  Channels: 1 = grayscale, 3 = BGR, 4 = BGRA

	Immediately after the header come width × height × channels bytes of
	raw uint8 pixel data in row-major order (top-left first):
	  • 1 ch : grayscale
	  • 3 ch : packed B G R per pixel
	  • 4 ch : packed B G R A per pixel

	A client may send multiple images over a single connection; the server
	reads them sequentially until the connection is closed.
	"""

	image_received = QtCore.pyqtSignal(QtGui.QPixmap)

	_MAGIC          = b'WIMG'
	_HEADER         = struct.Struct('<4sIII')   # magic, width, height, channels
	_VALID_CHANNELS = {1, 3, 4}

	def __init__(self, host='0.0.0.0', port=14972, parent=None):
		super().__init__(parent)
		self._host    = host
		self._port    = port
		self._running = False

	def run(self):
		self._running = True
		try:
			srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			srv.bind((self._host, self._port))
			srv.listen(1)
			srv.settimeout(1.0)
		except OSError as exc:
			print(f'ImageReceiver: bind failed on {self._host}:{self._port}: {exc}',
			      file=sys.stderr)
			return

		try:
			while self._running:
				try:
					conn, _ = srv.accept()
				except TimeoutError:
					continue
				except OSError:
					break
				try:
					self._handle(conn)
				finally:
					conn.close()
		finally:
			srv.close()

	def stop(self):
		self._running = False
		self.wait()

	# ------------------------------------------------------------------

	def _handle(self, conn):
		conn.settimeout(5.0)
		hdr_size = self._HEADER.size
		while self._running:
			try:
				hdr_bytes = self._recv_exact(conn, hdr_size)
				magic, width, height, channels = self._HEADER.unpack(hdr_bytes)
			except OSError:
				break

			if (magic != self._MAGIC or channels not in self._VALID_CHANNELS
					or width == 0 or height == 0):
				break   # protocol error — drop connection

			try:
				data = self._recv_exact(conn, width * height * channels)
			except OSError:
				break

			pixmap = self._to_pixmap(data, width, height, channels)
			if pixmap is not None:
				self.image_received.emit(pixmap)

	@staticmethod
	def _recv_exact(sock, n):
		buf      = bytearray(n)
		view     = memoryview(buf)
		received = 0
		while received < n:
			chunk = sock.recv_into(view[received:], n - received)
			if chunk == 0:
				raise ConnectionError('connection closed')
			received += chunk
		return bytes(buf)

	@staticmethod
	def _to_pixmap(data, width, height, channels):
		import numpy as np
		arr = np.frombuffer(data, dtype=np.uint8).reshape(height, width, channels)
		if channels == 3:
			arr = arr[:, :, [2, 1, 0]]          # BGR → RGB
			fmt = QtGui.QImage.Format.Format_RGB888
		elif channels == 4:
			arr = arr[:, :, [2, 1, 0, 3]]       # BGRA → RGBA
			fmt = QtGui.QImage.Format.Format_RGBA8888
		else:
			fmt = QtGui.QImage.Format.Format_Grayscale8
		arr = np.ascontiguousarray(arr)
		img = QtGui.QImage(arr.data, width, height, arr.strides[0], fmt).copy()
		return QtGui.QPixmap.fromImage(img)


class MainWindow(QtWidgets.QMainWindow):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Image Watcher")
		self._image_widget = ImageWidget()
		self._is_panning = False
		self._last_pan_pos = None
		self._history_dir = os.path.join(os.path.expanduser("~"), ".watcher")
		self._history_items = []
		self._current_image_in_history = False
		self._pending_label = ""
		self._setup_menu_bar()
		self._setup_toolbar()
		self._setup_dock_panes()
		self._scroll = QtWidgets.QScrollArea()
		self._scroll.setWidget(self._image_widget)
		self._scroll.setWidgetResizable(False)
		self._scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
		self.setCentralWidget(self._scroll)
		self._image_widget.installEventFilter(self)
		self._load_persistent_history()
		self._restore_window_state()
		self._receiver = ImageReceiver()
		self._receiver.image_received.connect(
			lambda px: self.display_image(px, "Network frame")
		)
		self._receiver.start()

	def _restore_window_state(self):
		settings = QtCore.QSettings("watcher", "watcher")
		geometry = settings.value("window/geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)
		state = settings.value("window/state")
		if state is not None:
			self.restoreState(state)

	def _save_window_state(self):
		settings = QtCore.QSettings("watcher", "watcher")
		settings.setValue("window/geometry", self.saveGeometry())
		settings.setValue("window/state", self.saveState())

	def closeEvent(self, event):
		self._receiver.stop()
		self._save_window_state()
		super().closeEvent(event)

	def _can_pan_image(self):
		if not self._image_widget.is_zoomed():
			return False
		return (
			self._scroll.horizontalScrollBar().maximum() > 0
			or self._scroll.verticalScrollBar().maximum() > 0
		)

	def eventFilter(self, watched, event):
		if watched is self._image_widget:
			event_type = event.type()
			if event_type == QtCore.QEvent.Type.Wheel:
				if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
					hbar = self._scroll.horizontalScrollBar()
					vbar = self._scroll.verticalScrollBar()
					mouse_pos = event.position()
					viewport_x = mouse_pos.x() - hbar.value()
					viewport_y = mouse_pos.y() - vbar.value()

					anchored_pos = self._image_widget.zoom_at(mouse_pos, event.angleDelta().y())
					if anchored_pos is not None:
						hbar.setValue(int(round(anchored_pos.x() - viewport_x)))
						vbar.setValue(int(round(anchored_pos.y() - viewport_y)))

					event.accept()
					return True

			if event_type == QtCore.QEvent.Type.MouseButtonPress:
				if event.button() == QtCore.Qt.MouseButton.LeftButton and self._can_pan_image():
					self._is_panning = True
					self._last_pan_pos = event.globalPosition().toPoint()
					self._image_widget.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
					event.accept()
					return True

			elif event_type == QtCore.QEvent.Type.MouseMove:
				if self._is_panning and self._last_pan_pos is not None:
					new_pos = event.globalPosition().toPoint()
					delta = new_pos - self._last_pan_pos
					self._last_pan_pos = new_pos
					self._scroll.horizontalScrollBar().setValue(
						self._scroll.horizontalScrollBar().value() - delta.x()
					)
					self._scroll.verticalScrollBar().setValue(
						self._scroll.verticalScrollBar().value() - delta.y()
					)
					event.accept()
					return True

			elif event_type == QtCore.QEvent.Type.MouseButtonRelease:
				if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_panning:
					self._is_panning = False
					self._last_pan_pos = None
					self._image_widget.unsetCursor()
					event.accept()
					return True

			elif event_type == QtCore.QEvent.Type.ContextMenu:
				self._show_pixel_context_menu(event.pos(), event.globalPos())
				return True

			elif event_type == QtCore.QEvent.Type.Hide:
				if self._is_panning:
					self._is_panning = False
					self._last_pan_pos = None
					self._image_widget.unsetCursor()

		return super().eventFilter(watched, event)

	def _show_pixel_context_menu(self, widget_pos, global_pos):
		pixmap = self._image_widget.image_pixmap()
		if pixmap is None or pixmap.isNull():
			return

		src_w = pixmap.width()
		src_h = pixmap.height()
		if src_w == 0 or src_h == 0:
			return

		# Derive display scale from the widget's current display pixmap.
		dp = self._image_widget._display_pixmap
		sx = dp.width() / src_w
		sy = dp.height() / src_h

		px = int(widget_pos.x() / sx)
		py = int(widget_pos.y() / sy)

		at_edge = not (1 <= px <= src_w - 2 and 1 <= py <= src_h - 2)
		zoom_ok = min(sx, sy) > 4.0

		menu = QtWidgets.QMenu(self)
		peak_action = menu.addAction("Sub-pixel peak")
		peak_action.setEnabled(zoom_ok and not at_edge)
		clear_action = menu.addAction("Clear peaks")
		clear_action.setEnabled(bool(self._image_widget._peak_markers))

		chosen = menu.exec(global_pos)
		if chosen is peak_action:
			image = pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_RGB32)
			dx, dy = self._compute_subpixel_peak(image, px, py)
			self._image_widget.add_peak_marker(px + dx, py + dy)
		elif chosen is clear_action:
			self._image_widget.clear_peak_markers()

	@staticmethod
	def _compute_subpixel_peak(image, px, py):
		"""Fit independent parabolas along x and y through the 3×3 neighbourhood.

		Returns (dx, dy) — the sub-pixel offset from (px, py) to the peak.
		"""
		def v(x, y):
			c = QtGui.QColor(image.pixel(x, y))
			return (c.red() + c.green() + c.blue()) / 3.0

		fc = v(px, py)

		# Horizontal parabola through the centre row
		fxm, fxp = v(px - 1, py), v(px + 1, py)
		denom_x = fxm - 2.0 * fc + fxp
		dx = (fxm - fxp) / (2.0 * denom_x) if denom_x != 0.0 else 0.0

		# Vertical parabola through the centre column
		fym, fyp = v(px, py - 1), v(px, py + 1)
		denom_y = fym - 2.0 * fc + fyp
		dy = (fym - fyp) / (2.0 * denom_y) if denom_y != 0.0 else 0.0

		return dx, dy

	def _convert_to_grayscale(self):
		pixmap = self._image_widget.image_pixmap()
		if pixmap is None or pixmap.isNull():
			return
		img = pixmap.toImage()
		gray_formats = {
			QtGui.QImage.Format.Format_Grayscale8,
			QtGui.QImage.Format.Format_Grayscale16,
		}
		if img.format() in gray_formats:
			QtWidgets.QMessageBox.information(self, "Convert to Grayscale",
			                                  "Image is already grayscale.")
			return
		gray = img.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
		self.display_image(QtGui.QPixmap.fromImage(gray), "Grayscale")

	def _open_feature_detection(self):
		pixmap = self._image_widget.image_pixmap()
		if pixmap is None or pixmap.isNull():
			QtWidgets.QMessageBox.information(self, "Feature Detection", "No image loaded.")
			return
		dlg = FeatureDetectionDialog(pixmap, self)
		dlg.detected.connect(self._apply_feature_keypoints)
		dlg.exec()

	def _apply_feature_keypoints(self, points):
		self._image_widget.set_peak_markers(points)

	def _setup_menu_bar(self):
		menu_bar = self.menuBar()

		file_menu = menu_bar.addMenu("&File")
		open_action = QtGui.QAction("&Open...", self)
		open_action.setShortcut(QtGui.QKeySequence("Ctrl+O"))
		open_action.triggered.connect(self._open_image_file)
		file_menu.addAction(open_action)

		edit_menu = menu_bar.addMenu("&Edit")
		copy_action = QtGui.QAction("&Copy", self)
		copy_action.setShortcut(QtGui.QKeySequence("Ctrl+C"))
		copy_action.triggered.connect(self._copy_image_to_clipboard)
		edit_menu.addAction(copy_action)

		paste_action = QtGui.QAction("&Paste", self)
		paste_action.setShortcut(QtGui.QKeySequence("Ctrl+V"))
		paste_action.triggered.connect(self._paste_image_from_clipboard)
		edit_menu.addAction(paste_action)

		algo_menu = menu_bar.addMenu("&Algorithms")
		feat_action = QtGui.QAction("&Feature detection...", self)
		feat_action.triggered.connect(self._open_feature_detection)
		algo_menu.addAction(feat_action)

		algo_menu.addSeparator()

		gray_action = QtGui.QAction("Convert to &Grayscale", self)
		gray_action.triggered.connect(self._convert_to_grayscale)
		algo_menu.addAction(gray_action)

	def _zoom_1_to_1(self):
		self._image_widget.set_scale_factor(1.0)
		self._image_widget.set_show_scaled(True)

	def _zoom_step(self, steps):
		vp = self._scroll.viewport()
		hbar = self._scroll.horizontalScrollBar()
		vbar = self._scroll.verticalScrollBar()
		cx = hbar.value() + vp.width() / 2.0
		cy = vbar.value() + vp.height() / 2.0
		anchor = self._image_widget.zoom_at(
			QtCore.QPointF(cx, cy), steps * 120
		)
		if anchor is not None:
			hbar.setValue(int(round(anchor.x() - vp.width() / 2.0)))
			vbar.setValue(int(round(anchor.y() - vp.height() / 2.0)))

	def _setup_toolbar(self):
		toolbar = self.addToolBar("Main")
		toolbar.setObjectName("mainToolbar")
		toolbar.setMovable(True)

		zoom_11_action = QtGui.QAction("1:1", self)
		zoom_11_action.setToolTip("Reset to 1:1 zoom")
		zoom_11_action.triggered.connect(self._zoom_1_to_1)
		toolbar.addAction(zoom_11_action)

		zoom_in_action = QtGui.QAction("+", self)
		zoom_in_action.setToolTip("Zoom in")
		zoom_in_action.triggered.connect(lambda: self._zoom_step(1))
		toolbar.addAction(zoom_in_action)

		zoom_out_action = QtGui.QAction("−", self)
		zoom_out_action.setToolTip("Zoom out")
		zoom_out_action.triggered.connect(lambda: self._zoom_step(-1))
		toolbar.addAction(zoom_out_action)

		toolbar.addSeparator()

		grid_action = QtGui.QAction(self._build_grid_icon(), "Toggle Grid", self)
		grid_action.setCheckable(True)
		grid_action.setChecked(False)
		grid_action.setToolTip("Toggle grid overlay")
		grid_action.toggled.connect(self._image_widget.set_show_grid)
		toolbar.addAction(grid_action)

		values_action = QtGui.QAction(self._build_values_icon(), "Toggle Values", self)
		values_action.setCheckable(True)
		values_action.setChecked(False)
		values_action.setToolTip("Toggle pixel intensity values (visible when zoom > 20×)")
		values_action.toggled.connect(self._image_widget.set_show_values)
		toolbar.addAction(values_action)

		toolbar.addSeparator()

		clear_peaks_action = QtGui.QAction(self._build_eraser_icon(), "Clear peaks", self)
		clear_peaks_action.setToolTip("Clear all peak markers")
		clear_peaks_action.triggered.connect(self._image_widget.clear_peak_markers)
		toolbar.addAction(clear_peaks_action)

		toolbar.addSeparator()

		self._save_to_history_action = QtGui.QAction("Save to History", self)
		self._save_to_history_action.setToolTip("Save the current image to history")
		self._save_to_history_action.setEnabled(False)
		self._save_to_history_action.triggered.connect(self._save_current_to_history)
		toolbar.addAction(self._save_to_history_action)

	def _build_eraser_icon(self):
		pixmap = QtGui.QPixmap(16, 16)
		pixmap.fill(QtCore.Qt.GlobalColor.transparent)

		painter = QtGui.QPainter(pixmap)
		painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

		# Eraser body — tilted parallelogram in pink/salmon
		body = QtGui.QPolygon([
			QtCore.QPoint(2, 13),
			QtCore.QPoint(6, 13),
			QtCore.QPoint(14, 5),
			QtCore.QPoint(10, 5),
		])
		painter.setPen(QtGui.QPen(QtGui.QColor(160, 80, 80), 1))
		painter.setBrush(QtGui.QBrush(QtGui.QColor(240, 150, 140)))
		painter.drawPolygon(body)

		# Dark band across the middle
		band = QtGui.QPolygon([
			QtCore.QPoint(6, 13),
			QtCore.QPoint(8, 13),
			QtCore.QPoint(14, 7),
			QtCore.QPoint(14, 5),
		])
		painter.setPen(QtCore.Qt.PenStyle.NoPen)
		painter.setBrush(QtGui.QBrush(QtGui.QColor(180, 100, 90)))
		painter.drawPolygon(band)

		# Flat bottom edge (erased stroke)
		painter.setPen(QtGui.QPen(QtGui.QColor(80, 80, 80), 1))
		painter.drawLine(2, 13, 6, 13)

		painter.end()
		return QtGui.QIcon(pixmap)

	def _build_values_icon(self):
		pixmap = QtGui.QPixmap(16, 16)
		pixmap.fill(QtCore.Qt.GlobalColor.transparent)

		painter = QtGui.QPainter(pixmap)
		painter.setPen(QtGui.QPen(QtGui.QColor(50, 50, 50), 1))
		painter.drawRect(1, 1, 13, 13)
		font = QtGui.QFont()
		font.setPixelSize(11)
		font.setBold(True)
		painter.setFont(font)
		painter.drawText(QtCore.QRect(1, 1, 13, 13), QtCore.Qt.AlignmentFlag.AlignCenter, "1")
		painter.end()

		return QtGui.QIcon(pixmap)

	def _build_grid_icon(self):
		pixmap = QtGui.QPixmap(16, 16)
		pixmap.fill(QtCore.Qt.GlobalColor.transparent)

		painter = QtGui.QPainter(pixmap)
		pen = QtGui.QPen(QtGui.QColor(50, 50, 50), 1)
		painter.setPen(pen)
		for i in (1, 5, 9, 13):
			painter.drawLine(i, 1, i, 14)
			painter.drawLine(1, i, 14, i)
		painter.end()

		return QtGui.QIcon(pixmap)

	def _setup_dock_panes(self):
		history_dock = QtWidgets.QDockWidget("History", self)
		history_dock.setObjectName("historyDock")
		history_dock.setAllowedAreas(
			QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
			| QtCore.Qt.DockWidgetArea.RightDockWidgetArea
		)

		container = QtWidgets.QWidget(history_dock)
		layout = QtWidgets.QVBoxLayout(container)
		layout.setContentsMargins(6, 6, 6, 6)
		layout.setSpacing(6)

		clear_button = QtWidgets.QPushButton("Clear History", container)
		clear_button.clicked.connect(self._clear_history)
		layout.addWidget(clear_button)

		self._history_list = QtWidgets.QListWidget(container)
		self._history_list.setIconSize(QtCore.QSize(96, 96))
		self._history_list.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
		self._history_list.setViewMode(QtWidgets.QListView.ViewMode.ListMode)
		self._history_list.setUniformItemSizes(False)
		self._history_list.itemActivated.connect(self._on_history_item_activated)
		self._history_list.itemClicked.connect(self._on_history_item_activated)
		self._history_list.setContextMenuPolicy(
			QtCore.Qt.ContextMenuPolicy.CustomContextMenu
		)
		self._history_list.customContextMenuRequested.connect(
			self._on_history_context_menu
		)
		layout.addWidget(self._history_list)

		history_dock.setWidget(container)
		self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, history_dock)

	def _ensure_history_dir(self):
		os.makedirs(self._history_dir, exist_ok=True)

	def _load_persistent_history(self):
		self._ensure_history_dir()
		supported_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
		paths = []
		for name in os.listdir(self._history_dir):
			path = os.path.join(self._history_dir, name)
			if os.path.isfile(path) and os.path.splitext(name)[1].lower() in supported_exts:
				paths.append(path)

		paths.sort(key=os.path.getmtime)
		for path in paths:
			pixmap = QtGui.QPixmap(path)
			if pixmap.isNull():
				continue
			self._add_image_to_history(pixmap, os.path.basename(path), file_path=path, persist=False)

	def _save_pixmap_to_history(self, pixmap):
		self._ensure_history_dir()
		file_name = f"{QtCore.QDateTime.currentDateTimeUtc().toMSecsSinceEpoch()}_{uuid.uuid4().hex}.png"
		path = os.path.join(self._history_dir, file_name)
		if pixmap.save(path, "PNG"):
			return path
		return None

	def _add_image_to_history(self, pixmap, label, file_path=None, persist=True):
		if pixmap is None or pixmap.isNull():
			return

		stored = pixmap.copy()
		if persist:
			file_path = self._save_pixmap_to_history(stored)

		entry = {
			"pixmap": stored,
			"path": file_path,
		}
		self._history_items.append(entry)
		index = len(self._history_items) - 1

		thumb = stored.scaled(
			96,
			96,
			QtCore.Qt.AspectRatioMode.KeepAspectRatio,
			QtCore.Qt.TransformationMode.SmoothTransformation,
		)
		item = QtWidgets.QListWidgetItem(QtGui.QIcon(thumb), f"{index + 1}: {label}")
		item.setData(QtCore.Qt.ItemDataRole.UserRole, index)
		self._history_list.addItem(item)
		self._history_list.setCurrentItem(item)

		self._current_image_in_history = True
		self._save_to_history_action.setEnabled(False)

	def _on_history_context_menu(self, pos):
		item = self._history_list.itemAt(pos)
		if item is None:
			return
		menu = QtWidgets.QMenu(self)
		remove_action = menu.addAction("Remove")
		if menu.exec(self._history_list.mapToGlobal(pos)) is remove_action:
			self._remove_history_item(item)

	def _remove_history_item(self, item):
		index = item.data(QtCore.Qt.ItemDataRole.UserRole)
		if index is None or not (0 <= index < len(self._history_items)):
			return
		entry = self._history_items.pop(index)
		path = entry.get("path")
		if path and os.path.isfile(path):
			try:
				os.remove(path)
			except OSError:
				pass
		self._history_list.takeItem(self._history_list.row(item))
		# Fix up stored indices for all items that followed the removed one.
		for i in range(self._history_list.count()):
			it = self._history_list.item(i)
			idx = it.data(QtCore.Qt.ItemDataRole.UserRole)
			if idx > index:
				it.setData(QtCore.Qt.ItemDataRole.UserRole, idx - 1)

	def _on_history_item_activated(self, item):
		if item is None:
			return

		index = item.data(QtCore.Qt.ItemDataRole.UserRole)
		if index is None:
			return

		if 0 <= index < len(self._history_items):
			self._image_widget.set_image(self._history_items[index]["pixmap"])
			self._current_image_in_history = True
			self._save_to_history_action.setEnabled(False)

	def _clear_history(self):
		self._history_items.clear()
		self._history_list.clear()
		shutil.rmtree(self._history_dir, ignore_errors=True)
		self._ensure_history_dir()
		if self._image_widget.image_pixmap() is not None:
			self._current_image_in_history = False
			self._save_to_history_action.setEnabled(True)

	def display_image(self, image, label=""):
		"""Display an image without adding it to history.

		Call this from high-frequency sources. Use the 'Save to History' toolbar
		button (or :meth:`_save_current_to_history`) to snapshot a frame manually.
		"""
		self._image_widget.set_image(image)
		self._pending_label = label
		self._current_image_in_history = False
		self._save_to_history_action.setEnabled(True)

	def _save_current_to_history(self):
		pixmap = self._image_widget.image_pixmap()
		if pixmap is None or pixmap.isNull():
			return
		self._add_image_to_history(pixmap, self._pending_label or "Saved frame")

	def _open_image_file(self):
		file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
			self,
			"Open Image",
			"",
			"Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All Files (*)",
		)
		if not file_path:
			return
		self._open_image_from_path(file_path)

	def _open_image_from_path(self, file_path):
		if not os.path.isfile(file_path):
			QtWidgets.QMessageBox.warning(self, "Open Image", f"File not found:\n{file_path}")
			return
		try:
			self._image_widget.set_image(file_path)
			self._add_image_to_history(self._image_widget.image_pixmap(), os.path.basename(file_path))
		except ValueError as exc:
			QtWidgets.QMessageBox.warning(self, "Open Image", str(exc))

	def _copy_image_to_clipboard(self):
		pixmap = self._image_widget.image_pixmap()
		if pixmap is None or pixmap.isNull():
			return

		QtWidgets.QApplication.clipboard().setPixmap(pixmap)

	def _paste_image_from_clipboard(self):
		clipboard = QtWidgets.QApplication.clipboard()
		pixmap = clipboard.pixmap()
		if pixmap is not None and not pixmap.isNull():
			self._image_widget.set_image(pixmap)
			self._add_image_to_history(self._image_widget.image_pixmap(), "Pasted image")
			return

		image = clipboard.image()
		if image is not None and not image.isNull():
			self._image_widget.set_image(image)
			self._add_image_to_history(self._image_widget.image_pixmap(), "Pasted image")


def main():
	app = QtWidgets.QApplication(sys.argv)
	window = MainWindow()
	window.show()
	app.processEvents()
	for path in sys.argv[1:]:
		window._open_image_from_path(path)
	sys.exit(app.exec())


if __name__ == "__main__":
	main()
