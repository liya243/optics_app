from __future__ import annotations
import sys, os, json, base64, glob
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsLineItem, QFileDialog, QLabel, QGraphicsPixmapItem,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox, QCheckBox, QMessageBox, QTreeWidget, QTreeWidgetItem, QLineEdit
)
from PySide6.QtCore import Qt, QPointF, QRectF, QBuffer, QByteArray, QIODevice, QSize, QEvent
from PySide6.QtGui import QPen, QPainterPath, QBrush, QColor, QPixmap, QPainter, QTransform, QImage, QIcon, QCursor, QKeySequence, QShortcut
import math

GRID_SIZE = 40
SCENE_WIDTH = 1000
SCENE_HEIGHT = 800

# Папка с компонентами (png) рядом с main.py
COMPONENTS_DIR_NAME = "components"

# ---- СЛОИ ----
LAYER_NAMES = ["Сетка", "Слой 0", "Слой 1", "Слой 2", "Слой 3", "Слой 4"]
LAYER_Z = {name: (-100 if name == "Сетка" else i * 10) for i, name in enumerate(LAYER_NAMES)}

def get_item_layer(item):
    return item.data(Qt.UserRole)

def set_item_layer(item, layer_name: str):
    item.setData(Qt.UserRole, layer_name)
    item.setZValue(LAYER_Z.get(layer_name, 0))


class DraggableComponent(QGraphicsRectItem):
    def __init__(self, label):
        super().__init__(0, 0, GRID_SIZE, GRID_SIZE)
        self.setBrush(QBrush(Qt.lightGray))
        self.setFlags(
            QGraphicsRectItem.ItemIsMovable |
            QGraphicsRectItem.ItemIsSelectable |
            QGraphicsRectItem.ItemSendsGeometryChanges
        )
        self.setTransformOriginPoint(GRID_SIZE / 2, GRID_SIZE / 2)
        self.setToolTip(label)
    def shape(self):
        path = QPainterPath()
        path.addRect(self.rect())
        return path
    def mouseReleaseEvent(self, event):
        sc = self.scene()
        if hasattr(sc, "group_snap") and sc.group_snap:
            # во время группового перетаскивания снэпом занимается GraphicsView
            super().mouseReleaseEvent(event)
            return
        # снэп центра к узлу сетки
        center_scene = self.mapToScene(self.transformOriginPoint())
        snapped_x = round(center_scene.x() / GRID_SIZE) * GRID_SIZE
        snapped_y = round(center_scene.y() / GRID_SIZE) * GRID_SIZE
        self.moveBy(snapped_x - center_scene.x(), snapped_y - center_scene.y())
        super().mouseReleaseEvent(event)

    def rotate_by(self, angle):
        self.setRotation(self.rotation() + angle)

    def flip_vertical(self):
        scene_center_before = self.mapToScene(self.transformOriginPoint())
        t = self.transform(); t.scale(1, -1)
        self.setTransform(t)
        scene_center_after = self.mapToScene(self.transformOriginPoint())
        delta = scene_center_before - scene_center_after
        self.moveBy(delta.x(), delta.y())


class ScalablePixmapItem(QGraphicsPixmapItem):
    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.setFlags(
            QGraphicsPixmapItem.ItemIsMovable |
            QGraphicsPixmapItem.ItemIsSelectable |
            QGraphicsPixmapItem.ItemSendsGeometryChanges
        )
        self.setTransformationMode(Qt.SmoothTransformation)
        self.setOpacity(1.0)
        self.setTransformOriginPoint(
            self.boundingRect().width() / 2,
            self.boundingRect().height() / 2
        )

    def shape(self):
        # Возвращаем форму всего прямоугольника
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path
    def rotate_by(self, angle):
        self.setRotation(self.rotation() + angle)
    
    def mouseReleaseEvent(self, event):
        sc = self.scene()
        if hasattr(sc, "group_snap") and sc.group_snap:
            super().mouseReleaseEvent(event)
            return
        center_scene = self.mapToScene(self.transformOriginPoint())
        snapped_x = round(center_scene.x() / GRID_SIZE) * GRID_SIZE
        snapped_y = round(center_scene.y() / GRID_SIZE) * GRID_SIZE
        self.moveBy(snapped_x - center_scene.x(), snapped_y - center_scene.y())
        super().mouseReleaseEvent(event)

    def flip_vertical(self):
        scene_center_before = self.mapToScene(self.transformOriginPoint())
        t = self.transform(); t.scale(1, -1)
        self.setTransform(t)
        scene_center_after = self.mapToScene(self.transformOriginPoint())
        delta = scene_center_before - scene_center_after
        self.moveBy(delta.x(), delta.y())

    def change_opacity(self, delta):
        self.setOpacity(min(1.0, max(0.1, self.opacity() + delta)))


class LaserLine(QGraphicsLineItem):
    def __init__(self, x1, y1, x2, y2, color=Qt.red, width=2.5):
        super().__init__(x1, y1, x2, y2)
        self.setFlags(
            QGraphicsLineItem.ItemIsSelectable |
            QGraphicsLineItem.ItemIsMovable
        )
        pen = QPen(color, width)
        pen.setCosmetic(True)
        self.setPen(pen)


class GraphicsView(QGraphicsView):
    def __init__(self, scene, main_window):
        self._group_drag = False
        self._group_center_before = None
        self._group_dragging = False
        super().__init__(scene)
        self.main_window = main_window
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.drawing_line = False
        self._bg_pix = None  # фон, если задан
        self.line_start = QPointF()
    def _item_center_scene(self, it):
        try:
            return it.mapToScene(it.transformOriginPoint())
        except Exception:
            return it.sceneBoundingRect().center()
    def set_background(self, path: str):
        pm = QPixmap(path)
        self._bg_pix = pm if not pm.isNull() else None
        self.viewport().update()

    def drawBackground(self, painter, rect):
        # 1) фон на весь виджет (включая области вне сцены)
        if self._bg_pix:
            painter.save()
            painter.resetTransform()  # рисуем в координатах виджета
            painter.drawPixmap(self.viewport().rect(), self._bg_pix, self._bg_pix.rect())
            painter.restore()

        # 2) белая подложка ТОЛЬКО под область сцены (чтобы сетка была на белом)
        # после restore у painter снова стандартный трансформ: scene <-> view
        scene_rect = self.scene().sceneRect()
        painter.fillRect(scene_rect, Qt.white)

        # 2.5) сетка (если включена)
        mw = self.main_window
        if getattr(mw, "grid_visible", True):
            pen = QPen(QColor(230, 230, 230))
            step = GRID_SIZE
            left = math.floor(scene_rect.left() / step) * step
            right = math.ceil(scene_rect.right() / step) * step
            top = math.floor(scene_rect.top() / step) * step
            bottom = math.ceil(scene_rect.bottom() / step) * step
            for x in range(int(left), int(right) + 1, step):
                painter.setPen(pen); painter.drawLine(x, scene_rect.top(), x, scene_rect.bottom())
            for y in range(int(top), int(bottom) + 1, step):
                painter.setPen(pen); painter.drawLine(scene_rect.left(), y, scene_rect.right(), y)

    def wheelEvent(self, event):
        # Реализуем зум как у Ctrl+±:
        #  - если выделены PNG -> Ctrl+колесо меняет масштаб PNG
        #  - иначе Ctrl+колесо масштабирует весь вид
        if event.modifiers() & Qt.ControlModifier:
            # Учитываем и обычные мыши (angleDelta), и тачпады (pixelDelta)
            dy = event.angleDelta().y()
            if dy == 0 and hasattr(event, "pixelDelta"):
                dy = event.pixelDelta().y()

            if dy == 0:
                event.ignore()
                return

            zoom_in = dy > 0
            factor = 1.15 if zoom_in else 1 / 1.15

            selected_items = self.scene().selectedItems()
            # Если выделены PNG — масштабируем их
            if selected_items:
                scaled_any = False
                for item in selected_items:
                    if isinstance(item, ScalablePixmapItem):
                        item.setScale(item.scale() * factor)
                        scaled_any = True
                if scaled_any:
                    event.accept()
                    return

            # Иначе — масштабируем вид
            self.scale(factor, factor)
            event.accept()
            return

        # Без Ctrl — стандартное поведение (скролл/прокрутка)
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.drawing_line = True
            self.line_start = self.mapToScene(event.position().toPoint())

        # старт группового перетаскивания (левая кнопка)
        if event.button() == Qt.LeftButton:
            sel = [it for it in self.scene().selectedItems()
                   if isinstance(it, (DraggableComponent, ScalablePixmapItem))]
            if sel:
                # запоминаем центр ограничивающего прямоугольника выделения
                group_rect = sel[0].sceneBoundingRect()
                for it in sel[1:]:
                    group_rect = group_rect.united(it.sceneBoundingRect())
                self._group_center_before = group_rect.center()
                # включаем флаг для подавления пер-элементного снэпа
                if len(sel) >= 2 and hasattr(self.scene(), "group_snap"):
                    self.scene().group_snap = True
            else:
                self._group_center_before = None
                if hasattr(self.scene(), "group_snap"):
                    self.scene().group_snap = False
        super().mousePressEvent(event)

    
    def _maybe_delete_items_dragged_left(self):
        """Удаляем только выделённые элементы, если они полностью ушли за левую грань viewport."""
        sel = [it for it in self.scene().selectedItems()
               if isinstance(it, (DraggableComponent, ScalablePixmapItem, LaserLine))]
        if not sel:
            return

        to_remove = []
        for item in sel:
            vr = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
            # при желании можно добавить порог, например vr.right() < -20
            if vr.right() < 0:
                to_remove.append(item)

        for it in to_remove:
            self.scene().removeItem(it)
            del it


    def mouseReleaseEvent(self, event):
        if self.drawing_line and event.button() == Qt.RightButton:
            end_point = self.mapToScene(event.position().toPoint())
            line = LaserLine(self.line_start.x(), self.line_start.y(),
                             end_point.x(), end_point.y())
            self.main_window.assign_to_active_layer(line)
            self.scene().addItem(line)
            self.drawing_line = False

        if event.button() == Qt.LeftButton and self._group_center_before is not None:
            sel = [it for it in self.scene().selectedItems()
                   if isinstance(it, (DraggableComponent, ScalablePixmapItem))]
            if sel:
                # текущее положение центра выделения
                group_rect = sel[0].sceneBoundingRect()
                for it in sel[1:]:
                    group_rect = group_rect.united(it.sceneBoundingRect())
                center_now = group_rect.center()

                # фактическое смещение пользователя
                move_dx = center_now.x() - self._group_center_before.x()
                move_dy = center_now.y() - self._group_center_before.y()

                # корректировка смещения до кратности GRID_SIZE
                corr_dx = round(move_dx / GRID_SIZE) * GRID_SIZE - move_dx
                corr_dy = round(move_dy / GRID_SIZE) * GRID_SIZE - move_dy

                if corr_dx or corr_dy:
                    for it in sel:
                        it.moveBy(corr_dx, corr_dy)

            self._group_center_before = None
            if hasattr(self.scene(), "group_snap"):
                self.scene().group_snap = False
            self._maybe_delete_items_dragged_left()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        # Быстрые подсказки
        if event.key() == Qt.Key_H:
            self.main_window.help_overlay.toggle()
            return
        if event.key() == Qt.Key_Escape:
            if self.main_window.help_overlay.isVisible():
                self.main_window.help_overlay.hide()
                return

        if event.key() == Qt.Key_F1:
            self.main_window.show_shortcuts()
            return

        selected_items = self.scene().selectedItems()
        angle_step = 22.5
        scale_step = 1.1

        # Зум вида
        if event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Plus, Qt.Key_Equal):
                if not selected_items:
                    self.scale(scale_step, scale_step)
                else:
                    for item in selected_items:
                        if isinstance(item, ScalablePixmapItem):
                            item.setScale(item.scale() * scale_step)
                return
            elif event.key() == Qt.Key_Minus:
                if not selected_items:
                    self.scale(1 / scale_step, 1 / scale_step)
                else:
                    for item in selected_items:
                        if isinstance(item, ScalablePixmapItem):
                            item.setScale(item.scale() / scale_step)
                return
            elif event.key() == Qt.Key_0:
                self.setTransform(QTransform())
                return

        # Смена слоя
        if event.key() == Qt.Key_PageUp:
            self.main_window.bump_selected_layer(+1)
            return
        elif event.key() == Qt.Key_PageDown:
            self.main_window.bump_selected_layer(-1)
            return

        # Удаление
        if event.key() == Qt.Key_Delete:
            for item in selected_items:
                if isinstance(item, (DraggableComponent, ScalablePixmapItem, LaserLine)):
                    self.scene().removeItem(item)
            return

        # Трансформации
        for item in selected_items:
            if event.key() == Qt.Key_R:
                direction = -1 if event.modifiers() & Qt.ShiftModifier else 1
                if hasattr(item, 'rotate_by'):
                    item.rotate_by(angle_step * direction)
            elif event.key() == Qt.Key_V:
                if hasattr(item, 'flip_vertical'):
                    item.flip_vertical()
            elif event.key() == Qt.Key_BracketLeft and hasattr(item, 'change_opacity'):
                item.change_opacity(-0.1)
            elif event.key() == Qt.Key_BracketRight and hasattr(item, 'change_opacity'):
                item.change_opacity(+0.1)

        super().keyPressEvent(event)

class HelpOverlay(QWidget):
    """Полупрозрачный overlay-виджет поверх QGraphicsView.viewport(). 
    Прозрачен для мыши, показывает подсказки. Переключается H."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet("""
            QLabel#title { font-weight: 600; }
            QLabel { color: #222; }
            QWidget#panel {
                background: rgba(255,255,255,200);
                border: 1px solid rgba(0,0,0,60);
                border-radius: 10px;
            }
        """)
        self.compact = True  # стартовый маленький режим

        self.panel = QWidget(self)
        self.panel.setObjectName("panel")
        v = QVBoxLayout(self.panel); v.setContentsMargins(12,10,12,10); v.setSpacing(6)

        self.title = QLabel("Подсказки"); self.title.setObjectName("title")
        self.body = QLabel(self._compact_text()); self.body.setTextFormat(Qt.RichText); self.body.setWordWrap(True)

        v.addWidget(self.title)
        v.addWidget(self.body)

        # следим за размером родителя, чтобы держаться в правом верхнем углу
        if self.parent():
            self.parent().installEventFilter(self)
        self._rebuild()

        self.show()  # показываем сразу (компактно)

    def _compact_text(self):
        return 'Нажми <b>H</b> — показать/скрыть горячие клавиши.'

    def _full_text(self):
        return (
            "<b>Навигация</b><br>"
            "Ctrl + / Ctrl - — зум вида; Ctrl 0 — сброс<br><br>"
            "<b>Рисование</b><br>"
            "ПКМ: нажать в A → отпустить в B — лазерный луч<br><br>"
            "<b>Объекты (выделенные)</b><br>"
            "R / Shift+R — поворот на 22.5° / в обратную<br>"
            "V — вертикальное отражение (относительно центра)<br>"
            "[  и  ] — прозрачность PNG<br>"
            "Ctrl + / Ctrl - — масштаб PNG (если PNG выделен)<br>"
            "Ctrl+C / Ctrl+V — копировать / вставить<br>"
            "Ctrl+D — дублировать рядом<br>"
            "Delete — удалить; PageUp/PageDown — слой выше/ниже<br>"
            "Перетащить за левую границу — удалить<br><br>"
            "<b>Файл</b><br>"
            "Ctrl+S — сохранить проект; Ctrl+O — открыть; Ctrl+E — экспорт PNG"
        )

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Resize:
            self._rebuild()
        return super().eventFilter(obj, ev)

    def _rebuild(self):
        # размеры панели в зависимости от режима
        if self.compact:
            maxw = 280
            self.body.setText(self._compact_text())
        else:
            maxw = 460
            self.body.setText(self._full_text())

        self.panel.setFixedWidth(maxw)
        self.panel.adjustSize()
        self.resize(self.panel.size())

        # позиционируем в правом верхнем углу родителя с отступом
        margin = 12
        pw = self.parent().width() if self.parent() else 800
        self.move(pw - self.width() - margin, margin)

    def toggle(self):
        # переключаем компактный/полный режим
        self.compact = not self.compact
        self._rebuild()
        if not self.isVisible():
            self.show()


# ДО импорта MainWindow
class Scene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.group_snap = False  # идет ли групповое перетаскивание



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Оптический редактор (v1.2)")
        self.setMinimumSize(1300, 880)
        self.grid_visible = True
        self.scene_width = SCENE_WIDTH
        self.scene_height = SCENE_HEIGHT
        self.scene = Scene()
        self.scene.setSceneRect(0, 0, self.scene_width, self.scene_height)
        # в MainWindow.__init__
        self.view = GraphicsView(self.scene, self)
        # Оверлей помощи поверх области рисования
        self.help_overlay = HelpOverlay(self.view.viewport())

        self.view.setDragMode(QGraphicsView.RubberBandDrag)

        # ==== Левая панель ====
        # Поиск
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск компонентов…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.apply_component_filter)

        # Дерево компонентов (категории = папки)
        self.component_tree = QTreeWidget()
        self.component_tree.setHeaderHidden(True)
        self.component_tree.itemDoubleClicked.connect(self.add_component_to_scene)
        self.component_tree.setIconSize(QSize(40, 40))

        # Кнопка обновления списка
        self.refresh_components_btn = QPushButton("Обновить список")
        self.refresh_components_btn.clicked.connect(self.populate_components_tree)

        # Путь к папке с компонентами (покажем текстом)
        self.components_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), COMPONENTS_DIR_NAME)
        self.components_path_label = QLabel(f"Папка: {self.components_dir}")


        # Ручная загрузка PNG (оставим)
        self.load_png_button = QPushButton("Добавить PNG (файл)")
        self.load_png_button.clicked.connect(self.load_png)

        self.layer_combo = QComboBox()
        self.layer_combo.addItems([n for n in LAYER_NAMES if n != "Сетка"])
        self.layer_combo.setCurrentText("Слой 1")

        self.layers_list = QListWidget()
        for name in LAYER_NAMES:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.layers_list.addItem(it)
        self.layers_list.itemChanged.connect(self.apply_layer_visibility)

        # Контролы размера холста
        self.canvas_w_spin = QSpinBox(); self.canvas_w_spin.setRange(200, 20000); self.canvas_w_spin.setSingleStep(100); self.canvas_w_spin.setValue(self.scene_width)
        self.canvas_h_spin = QSpinBox(); self.canvas_h_spin.setRange(200, 20000); self.canvas_h_spin.setSingleStep(100); self.canvas_h_spin.setValue(self.scene_height)
        self.apply_canvas_btn = QPushButton("Применить размер")
        self.apply_canvas_btn.clicked.connect(self.apply_canvas_size_from_ui)

        # Экспорт
        self.export_without_grid_cb = QCheckBox("Без сетки при экспорте"); self.export_without_grid_cb.setChecked(True)
        self.export_btn = QPushButton("Экспорт PNG"); self.export_btn.clicked.connect(self.export_canvas_png)

        # Сохранить/Открыть проект (JSON)
        self.save_btn = QPushButton("Сохранить проект…"); self.save_btn.clicked.connect(self.save_project_json)
        self.load_btn = QPushButton("Открыть проект…"); self.load_btn.clicked.connect(self.load_project_json)

        left_panel = QVBoxLayout()
        # внутреннее хранилище найденных png
        self._components = []  # список словарей: {"name": str, "path": str, "icon": QIcon}


        left_panel.addWidget(QLabel("Компоненты (из папки):"))
        left_panel.addWidget(self.components_path_label)
        left_panel.addWidget(self.refresh_components_btn)
        left_panel.addWidget(self.search_edit)
        left_panel.addWidget(self.component_tree)  # вместо списка
        left_panel.addSpacing(8)
        left_panel.addWidget(self.load_png_button)
        left_panel.addSpacing(10)
        left_panel.addWidget(QLabel("Активный слой (для новых объектов):"))
        left_panel.addWidget(self.layer_combo)
        left_panel.addSpacing(10)
        left_panel.addWidget(QLabel("Видимость слоёв:"))
        left_panel.addWidget(self.layers_list)
        left_panel.addSpacing(12)
        left_panel.addWidget(QLabel("Размер холста (px):"))
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Ширина")); size_row.addWidget(self.canvas_w_spin)
        size_row.addSpacing(6)
        size_row.addWidget(QLabel("Высота")); size_row.addWidget(self.canvas_h_spin)
        left_panel.addLayout(size_row)
        left_panel.addWidget(self.apply_canvas_btn)
        left_panel.addSpacing(10)
        left_panel.addWidget(self.export_without_grid_cb)
        left_panel.addWidget(self.export_btn)
        left_panel.addSpacing(10)
        left_panel.addWidget(self.save_btn)
        left_panel.addWidget(self.load_btn)
        left_panel.addStretch()

        layout = QHBoxLayout()
        left = QWidget(); left.setLayout(left_panel)
        layout.addWidget(left, 1)
        layout.addWidget(self.view, 4)

        container = QWidget()
        container.setLayout(layout)
        # имена для QSS
        left.setObjectName("LeftPanel")
        container.setObjectName("RootContainer")

        self.view.setBackgroundBrush(Qt.NoBrush)
        self.setCentralWidget(container)
        self.apply_background_theme()
        # Заполним список компонентов и нарисуем сетку
        # Меню «Справка»
        help_menu = self.menuBar().addMenu("Справка")
        act_help = help_menu.addAction("Горячие клавиши (F1)")
        act_help.triggered.connect(self.show_shortcuts)

        # Подсказка в статус-баре при старте
        self.statusBar().showMessage("F1 — горячие клавиши; Ctrl+S — сохранить; Ctrl+E — экспорт", 6000)

        # Горячие клавиши для часто используемых действий
        self._clipboard = None
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self.copy_selection)
        QShortcut(QKeySequence("Ctrl+V"), self, activated=self.paste_clipboard)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.duplicate_selection)
        QShortcut(QKeySequence("F1"), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_project_json)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.load_project_json)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.export_canvas_png)
        self.populate_components_tree()
    
    def iter_scene_items(self):
        """Перебирает все объекты сцены, которые являются элементами (а не вспомогательными объектами)."""
        for it in self.scene.items():
            if isinstance(it, (DraggableComponent, ScalablePixmapItem, LaserLine)):
                yield it

    def _view_center_scene(self) -> QPointF:
        # центр видимой области в координатах сцены
        vc = self.view.viewport().rect().center()
        return self.view.mapToScene(vc)

    def _snap_point(self, p: QPointF) -> QPointF:
        return QPointF(
            round(p.x() / GRID_SIZE) * GRID_SIZE,
            round(p.y() / GRID_SIZE) * GRID_SIZE
        )
    
    # --- КОПИРОВАНИЕ/ВСТАВКА ---

    def serialize_item(self, item) -> Optional[dict]:
        lname = get_item_layer(item)
        if isinstance(item, DraggableComponent):
            return {
                "type": "component",
                "label": item.toolTip(),
                "layer": lname,
                "pos": [item.pos().x(), item.pos().y()],
                "rotation": item.rotation(),
                "opacity": item.opacity(),
                "transform": self._transform_to_list(item.transform())
            }
        if isinstance(item, ScalablePixmapItem):
            return {
                "type": "png",
                "png_b64": self._pixmap_to_b64(item.pixmap()),
                "layer": lname,
                "pos": [item.pos().x(), item.pos().y()],
                "rotation": item.rotation(),
                "opacity": item.opacity(),
                "scale": item.scale(),
                "transform": self._transform_to_list(item.transform())
            }
        if isinstance(item, LaserLine):
            ln = item.line()
            p1 = item.mapToScene(ln.p1()); p2 = item.mapToScene(ln.p2())
            pen = item.pen()
            return {
                "type": "laser",
                "layer": lname,
                "p1": [p1.x(), p1.y()],
                "p2": [p2.x(), p2.y()],
                "color": [pen.color().red(), pen.color().green(), pen.color().blue(), pen.color().alpha()],
                "width": pen.widthF()
            }
        return None

    def instantiate_item(self, it: dict, delta: QPointF = QPointF(0, 0)) -> Optional[QGraphicsLineItem]:
        t = it.get("type"); lname = it.get("layer", "Слой 1")
        if t == "component":
            obj = DraggableComponent(it.get("label", "Компонент"))
            self.scene.addItem(obj)
            obj.setPos(it["pos"][0] + delta.x(), it["pos"][1] + delta.y())
            obj.setRotation(it.get("rotation", 0.0))
            obj.setOpacity(it.get("opacity", 1.0))
            obj.setTransform(self._transform_from_list(it.get("transform", [1,0,0,0,1,0,0,0,1])))
            set_item_layer(obj, lname); return obj

        if t == "png":
            try:
                pix = self._pixmap_from_b64(it.get("png_b64", ""))
            except Exception:
                return None
            obj = ScalablePixmapItem(pix); self.scene.addItem(obj)
            obj.setPos(it["pos"][0] + delta.x(), it["pos"][1] + delta.y())
            obj.setRotation(it.get("rotation", 0.0))
            obj.setOpacity(it.get("opacity", 1.0))
            obj.setScale(it.get("scale", 1.0))
            obj.setTransform(self._transform_from_list(it.get("transform", [1,0,0,0,1,0,0,0,1])))
            set_item_layer(obj, lname); return obj

        if t == "laser":
            p1 = it.get("p1", [0, 0]); p2 = it.get("p2", [0, 0])
            col = it.get("color", [255, 0, 0, 255])
            pen = QPen(QColor(*col), float(it.get("width", 2.5))); pen.setCosmetic(True)
            obj = LaserLine(p1[0] + delta.x(), p1[1] + delta.y(), p2[0] + delta.x(), p2[1] + delta.y())
            obj.setPen(pen); self.scene.addItem(obj)
            set_item_layer(obj, lname); return obj
        return None

    def copy_selection(self) -> None:
        """Копирует выделенные объекты в внутренний буфер (Ctrl+C)."""
        sel = [it for it in self.scene.selectedItems()
               if isinstance(it, (DraggableComponent, ScalablePixmapItem, LaserLine))]
        if not sel:
            return
        items = []
        for it in sel:
            d = self.serialize_item(it)
            if d:
                items.append(d)
        # можно добавить базовую точку, но сейчас не требуется
        self._clipboard = {"items": items}

    def _instantiate_from_dict(self, it: dict, delta: QPointF):
        """Создаёт объект из словаря (как при загрузке), смещая на delta."""
        t = it.get("type"); lname = it.get("layer", "Слой 1")
        if t == "component":
            obj = DraggableComponent(it.get("label", "Компонент"))
            self.scene.addItem(obj)
            obj.setPos(it["pos"][0] + delta.x(), it["pos"][1] + delta.y())
            obj.setRotation(it.get("rotation", 0.0))
            obj.setOpacity(it.get("opacity", 1.0))
            obj.setTransform(self._transform_from_list(it.get("transform", [1,0,0,0,1,0,0,0,1])))
            set_item_layer(obj, lname)
            return obj

        elif t == "png":
            try:
                pix = self._pixmap_from_b64(it.get("png_b64", ""))
            except Exception:
                return None
            obj = ScalablePixmapItem(pix)
            self.scene.addItem(obj)
            obj.setPos(it["pos"][0] + delta.x(), it["pos"][1] + delta.y())
            obj.setRotation(it.get("rotation", 0.0))
            obj.setOpacity(it.get("opacity", 1.0))
            obj.setScale(it.get("scale", 1.0))
            obj.setTransform(self._transform_from_list(it.get("transform", [1,0,0,0,1,0,0,0,1])))
            set_item_layer(obj, lname)
            return obj

        elif t == "laser":
            p1 = it.get("p1", [0, 0]); p2 = it.get("p2", [0, 0])
            col = it.get("color", [255, 0, 0, 255])
            pen = QPen(QColor(*col), float(it.get("width", 2.5))); pen.setCosmetic(True)
            obj = LaserLine(p1[0] + delta.x(), p1[1] + delta.y(),
                            p2[0] + delta.x(), p2[1] + delta.y())
            obj.setPen(pen)
            self.scene.addItem(obj)
            set_item_layer(obj, lname)
            return obj

        return None

    def _paste_with_delta(self, delta: QPointF):
        if not self._clipboard:
            return
        self.scene.clearSelection()
        for it in self._clipboard["items"]:
            obj = self._instantiate_from_dict(it, delta)
            if obj:
                obj.setSelected(True)
        self.apply_layer_visibility()

    def paste_clipboard(self) -> None:
        """Вставляет из буфера рядом со старым местом (Ctrl+V)."""
        if not self._clipboard:
            return
        # Сдвигаем на 1 шаг сетки, чтобы было видно дубликат
        self._paste_with_delta(QPointF(GRID_SIZE, GRID_SIZE))

    def duplicate_selection(self) -> None:
        """Быстрый дубликат рядом от исходного выделения (Ctrl+D)."""
        sel = self.scene.selectedItems()
        if not sel:
            return
        self.copy_selection()
        self._paste_with_delta(QPointF(GRID_SIZE, GRID_SIZE))


    def _place_item_at_view_center(self, item):
        # хотим, чтобы центр (transformOriginPoint) уехал в центр вида
        target = self._snap_point(self._view_center_scene())
        try:
            current_center = item.mapToScene(item.transformOriginPoint())
        except Exception:
            current_center = item.sceneBoundingRect().center()
        delta = target - current_center
        item.moveBy(delta.x(), delta.y())


    def populate_components_tree(self):
        """Рекурсивно сканирует COMPONENTS_DIR и строит дерево папок и PNG."""
        self.component_tree.clear()
        os.makedirs(self.components_dir, exist_ok=True)

        # Рекурсивный проход: dict {folder_path: QTreeWidgetItem}
        root_map = {}
        root_item = QTreeWidgetItem([os.path.basename(self.components_dir) or "components"])
        root_item.setData(0, Qt.UserRole, {"type": "folder", "path": self.components_dir})
        root_item.setIcon(0, QIcon.fromTheme("folder"))
        self.component_tree.addTopLevelItem(root_item)
        root_map[self.components_dir] = root_item

        for dirpath, dirnames, filenames in os.walk(self.components_dir):
            # создаём узлы для подпапок
            parent_item = root_map.get(dirpath, None)
            if parent_item is None:
                # на случай, если обход начался не с корня
                parent_item = QTreeWidgetItem([os.path.basename(dirpath)])
                parent_item.setData(0, Qt.UserRole, {"type": "folder", "path": dirpath})
                parent_item.setIcon(0, QIcon.fromTheme("folder"))
                self.component_tree.addTopLevelItem(parent_item)
                root_map[dirpath] = parent_item

            # подпапки
            for d in sorted(dirnames):
                full = os.path.join(dirpath, d)
                item = QTreeWidgetItem([d])
                item.setData(0, Qt.UserRole, {"type": "folder", "path": full})
                item.setIcon(0, QIcon.fromTheme("folder"))
                parent_item.addChild(item)
                root_map[full] = item

            # PNG файлы в текущей папке
            pngs = sorted([f for f in filenames if f.lower().endswith(".png")])
            for f in pngs:
                full = os.path.join(dirpath, f)
                name = os.path.splitext(f)[0]
                leaf = QTreeWidgetItem([name])
                leaf.setData(0, Qt.UserRole, {"type": "png_component", "path": full, "name": name})
                pm = QPixmap(full)
                if not pm.isNull():
                    leaf.setIcon(0, QIcon(pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                parent_item.addChild(leaf)

        self.component_tree.expandItem(root_item)  # корень раскрыт
        self.apply_component_filter(self.search_edit.text())  # применим текущий фильтр
    def apply_component_filter(self, text: str):
        """Показывает/скрывает элементы дерева по подстроке (без учета регистра)."""
        query = (text or "").strip().lower()

        def match(item: QTreeWidgetItem) -> bool:
            meta = item.data(0, Qt.UserRole) or {}
            name = item.text(0).lower()
            is_folder = meta.get("type") == "folder"
            if not query:
                return True  # показать всё
            if not is_folder:
                return query in name
            # папка видима, если видим хоть один дочерний
            for i in range(item.childCount()):
                if match(item.child(i)):
                    return True
            return False

        def apply(item: QTreeWidgetItem):
            visible = match(item)
            item.setHidden(not visible)  # <<<< ключевая замена
            # если папка видима и есть запрос — раскроем её
            meta = item.data(0, Qt.UserRole) or {}
            if meta.get("type") == "folder":
                if visible and query:
                    item.setExpanded(True)
                # рекурсивно на детей
                for i in range(item.childCount()):
                    apply(item.child(i))

        # ускорим массовое обновление
        self.component_tree.setUpdatesEnabled(False)
        for i in range(self.component_tree.topLevelItemCount()):
            apply(self.component_tree.topLevelItem(i))
        self.component_tree.setUpdatesEnabled(True)


    def show_shortcuts(self):
        QMessageBox.information(self, "Горячие клавиши", 
         "<b>Навигация</b><br>"
         "Ctrl + / Ctrl - — зум вида<br>"
         "Ctrl 0 — сброс зума<br>"
         "<br>"
         "<b>Рисование</b><br>"
         "ПКМ: нажать в точке A → отпустить в точке B — создать лазерный луч<br>"
         "<br>"
         "<b>Объекты (выделенные)</b><br>"
         "R / Shift+R — поворот на 22.5° / в обратную сторону<br>"
         "V — отражение по вертикали (относительно центра)<br>"
         "[  и  ] — уменьшить/увеличить прозрачность PNG<br>"
         "Ctrl + / Ctrl - — масштаб PNG (если PNG выделен)<br>"
         "Ctrl+C / Ctrl+V — копировать / вставить<br>"
         "Ctrl+D — дублировать рядом<br>"
         "Delete — удаление<br>"
         "PageUp / PageDown — слой выше / ниже<br>"
         "Перетащить за левую границу — удалить<br>"
         "<br>"
         "<b>Файл</b><br>"
         "Ctrl+S — сохранить проект (JSON)<br>"
            "Ctrl+O — открыть проект (JSON)<br>"
            "Ctrl+E — экспорт PNG<br>"
        )
    def apply_background_theme(self):
        """Ставит background.png как фон окна, левую панель делает полупрозрачной."""
        app_dir = os.path.dirname(os.path.abspath(__file__))
        bg_path = os.path.join(app_dir, "background.png")
        if not os.path.exists(bg_path):
            return

        bg_url = bg_path.replace("\\", "/")

        root_qss = f'''
        QWidget#RootContainer {{
            border-image: url("{bg_url}") 0 0 0 0 stretch stretch;
        }}'''

        left_qss = """
        QWidget#LeftPanel {
            background: rgba(255, 255, 255, 200);
            border-radius: 10px;
        }
        """

        # фон для области рисования — через сам GraphicsView
        self.view.set_background(bg_path)

        # применяем общий стиль
        self.setStyleSheet(root_qss + left_qss)
        self.view.setBackgroundBrush(Qt.NoBrush)

    def active_layer_name(self) -> str:
        return self.layer_combo.currentText()

    def assign_to_active_layer(self, item):
        set_item_layer(item, self.active_layer_name())

    def apply_layer_visibility(self):
        visible = {}
        for i in range(self.layers_list.count()):
            it = self.layers_list.item(i)
            visible[it.text()] = (it.checkState() == Qt.Checked)
        for item in self.scene.items():
            lname = get_item_layer(item)
            if lname is None:
                continue
            item.setVisible(visible.get(lname, True))

    def bump_selected_layer(self, delta: int):
        user_layers = [n for n in LAYER_NAMES if n != "Сетка"]
        for item in self.scene.selectedItems():
            lname = get_item_layer(item)
            if lname not in user_layers:
                lname = self.active_layer_name()
            idx = user_layers.index(lname)
            new_idx = max(0, min(len(user_layers) - 1, idx + delta))
            new_name = user_layers[new_idx]
            set_item_layer(item, new_name)
        self.apply_layer_visibility()

    # --- ХОЛСТ ---
    def apply_canvas_size_from_ui(self):
        w = int(self.canvas_w_spin.value())
        h = int(self.canvas_h_spin.value())
        self.set_canvas_size(w, h)
    def redraw_grid(self):
        """Перерисовать сетку/фон (обновляем viewport)."""
        if hasattr(self, "view") and self.view is not None:
            self.view.viewport().update()
     
    def set_canvas_size(self, w: int, h: int):
        # старый центр сцены
        old_rect = self.scene.sceneRect()
        old_center = old_rect.center()

        # новый прямоугольник с тем же центром
        new_rect = QRectF(
            old_center.x() - w / 2,
            old_center.y() - h / 2,
            w,
            h
        )
        self.scene_width = w
        self.scene_height = h
        self.scene.setSceneRect(new_rect)

        # держим «камеру» на прежнем центре
        self.view.centerOn(old_center)

        # перерисовать сетку с учётом смещения/отрицательных координат
        self.redraw_grid()


    # --- ЭКСПОРТ PNG ---
    def export_canvas_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить PNG", "optical_scheme.png", "PNG Files (*.png)")
        if not path:
            return

        hidden_grid = False
        if self.export_without_grid_cb.isChecked() and self.grid_visible:
            hidden_grid = True
            self.set_grid_visible(False)
        rect = self.scene.sceneRect()  # используем реальный прямоугольник сцены
        img = QImage(int(rect.width()), int(rect.height()), QImage.Format_ARGB32)
        img.fill(Qt.white)

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        # target — (0,0,w,h) картинки, source — реальный прямоугольник сцены
        self.scene.render(p, target=QRectF(0, 0, rect.width(), rect.height()), source=rect)
        p.end()
        img.save(path, "PNG")

        if hidden_grid:
            self.set_grid_visible(True)

    def set_grid_visible(self, visible: bool):
        self.grid_visible = visible
        self.view.viewport().update()

    # --- ДОБАВЛЕНИЕ ---
    def add_component_to_scene(self, item):
        """Обрабатывает двойной клик по элементу (лист png)."""
        # item может быть QTreeWidgetItem или QListWidgetItem — приведём к общему доступу
        meta = None
        # QTreeWidgetItem
        if hasattr(item, "data"):
            meta = item.data(0, Qt.UserRole)
        # QListWidgetItem fallback (если где-то ещё зовётся)
        if meta is None and isinstance(item, QListWidgetItem):
            meta = item.data(Qt.UserRole)

        if not isinstance(meta, dict):
            return

        if meta.get("type") == "png_component":
            path = meta.get("path", "")
            pm = QPixmap(path)
            if pm.isNull():
                return
            obj = ScalablePixmapItem(pm)
            obj.setToolTip(meta.get("name", os.path.basename(path)))
            self.scene.addItem(obj)
            self.assign_to_active_layer(obj)
            self._place_item_at_view_center(obj)
        # по папке ничего не делаем (можно позже сделать добавление всей папки на слой)

    def load_png(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выбери PNG", "", "PNG Files (*.png)")
        if file_path:
            pixmap = QPixmap(file_path)
            if pixmap.isNull():
                return
            item = ScalablePixmapItem(pixmap)
            item.setToolTip(os.path.splitext(os.path.basename(file_path))[0])
            self.scene.addItem(item)
            self.assign_to_active_layer(item)
            self._place_item_at_view_center(item)

    # === СЕРИАЛИЗАЦИЯ/ДЕСЕРИАЛИЗАЦИЯ ПРОЕКТА ===
    def _pixmap_to_b64(self, pixmap: QPixmap) -> str:
        img = pixmap.toImage()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        return base64.b64encode(bytes(ba)).decode("ascii")

    def _pixmap_from_b64(self, data_b64: str) -> QPixmap:
        raw = base64.b64decode(data_b64.encode("ascii"))
        ba = QByteArray(raw)
        img = QImage.fromData(ba, "PNG")
        return QPixmap.fromImage(img)

    def _transform_to_list(self, t: QTransform):
        return [t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33()]

    def _transform_from_list(self, lst):
        return QTransform(lst[0], lst[1], lst[2],
                          lst[3], lst[4], lst[5],
                          lst[6], lst[7], lst[8])

    def save_project_json(self) -> None:
        """Сохраняет все объекты сцены в JSON (Ctrl+S)."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить проект", "project.json", "JSON Files (*.json)"
        )
        if not path:
            return

        items = []
        for it in self.iter_scene_items():
            d = self.serialize_item(it)
            if d:
                items.append(d)

        data = {
            "scene": {"width": self.scene_width, "height": self.scene_height},
            "items": items,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_project_json(self) -> None:
        """Открывает проект из JSON (Ctrl+O)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть проект", "", "JSON Files (*.json)"
        )
        if not path:
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # очистим сцену и перерисуем сетку под новые размеры
        self.scene.clear()

        sc = data.get("scene", {})
        w = int(sc.get("width", self.scene_width))
        h = int(sc.get("height", self.scene_height))
        self.set_canvas_size(w, h)

        for it in data.get("items", []):
            self.instantiate_item(it, QPointF(0, 0))

        # вернуть видимость слоёв по текущим флажкам
        self.apply_layer_visibility()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

