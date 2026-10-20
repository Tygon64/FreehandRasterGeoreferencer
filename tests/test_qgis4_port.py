"""Headless smoke test of the QGIS 4 port: plugin start, every tool, layer load, transform, export, undo.

Run with QGIS's Python, e.g.:  "C:\\Program Files\\QGIS 4.2.3\\bin\\python-qgis.bat" tests\\test_qgis4_port.py
"""
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = tempfile.mkdtemp(prefix="frg_")
PKG = os.path.join(PARENT, "FreehandRasterGeoreferencer")
shutil.copytree(ROOT, PKG, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__"))
sys.path.insert(0, PARENT)

from qgis.testing import start_app  # noqa: E402
from qgis.testing.mocked import get_iface  # noqa: E402

APP = start_app()

import numpy as np  # noqa: E402
from osgeo import gdal, osr  # noqa: E402
from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsProject, QgsRectangle  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QPoint, Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMessageBox  # noqa: E402
from qgis.gui import QgsMapMouseEvent  # noqa: E402

failures = []


def check(name, fn):
    try:
        out = fn()
        print("OK  ", name, "" if out is None else out)
    except Exception:
        failures.append(name)
        print("FAIL", name)
        traceback.print_exc()


# ---- test images: a TIFF (RGB) and a PNG
tif = os.path.join(PARENT, "scan.tif")
ds = gdal.GetDriverByName("GTiff").Create(tif, 300, 200, 3, gdal.GDT_Byte)
for b in range(3):
    ds.GetRasterBand(b + 1).WriteArray((np.random.rand(200, 300) * 255).astype(np.uint8))
ds = None
png = os.path.join(PARENT, "scan.png")
from qgis.PyQt.QtGui import QColor, QImage  # noqa: E402
img = QImage(120, 80, QImage.Format.Format_RGB32); img.fill(QColor(30, 140, 220)); img.save(png)

iface = get_iface()
canvas = iface.mapCanvas()
canvas.resize(800, 600)
QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:32736"))
canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32736"))
canvas.setExtent(QgsRectangle(250000, 6720000, 254000, 6723000))

import FreehandRasterGeoreferencer as frg_pkg  # noqa: E402
from FreehandRasterGeoreferencer.freehandrastergeoreferencer_layer import FreehandRasterGeoreferencerLayer  # noqa: E402
from FreehandRasterGeoreferencer.freehandrastergeoreferencer_commands import ExportGeorefRasterCommand  # noqa: E402

plugin = frg_pkg.classFactory(iface)
check("initGui (creates all actions and map tools)", plugin.initGui)

layers = {}


def add(path, key):
    lyr = FreehandRasterGeoreferencerLayer(plugin, path, os.path.basename(path), canvas.extent())
    assert lyr.isValid(), "layer not valid"
    QgsProject.instance().addMapLayer(lyr)
    layers[key] = lyr
    return f"{lyr.image.width()}x{lyr.image.height()} center={lyr.center}"


check("load TIFF as freehand layer", lambda: add(tif, "tif"))
check("load PNG as freehand layer", lambda: add(png, "png"))

lyr = layers.get("tif")
if lyr:
    # make the mocked iface behave like QGIS: active layer + layer tree panel
    import types
    iface.activeLayer = lambda: lyr
    root = QgsProject.instance().layerTreeRoot()
    iface.layerTreeView = lambda: types.SimpleNamespace(layerTreeModel=lambda: types.SimpleNamespace(rootGroup=lambda: root))
    plugin.currentLayerChanged(lyr)   # what QGIS's currentLayerChanged signal does when you click the layer

    def render():
        from qgis.core import QgsMapRendererParallelJob, QgsMapSettings
        from qgis.PyQt.QtCore import QSize
        ms = QgsMapSettings(); ms.setLayers([lyr]); ms.setDestinationCrs(canvas.mapSettings().destinationCrs())
        ms.setExtent(canvas.extent()); ms.setOutputSize(QSize(400, 300))
        job = QgsMapRendererParallelJob(ms); job.start(); job.waitForFinished()
        im = job.renderedImage()
        nonwhite = sum(1 for x in range(0, 400, 10) for y in range(0, 300, 10) if im.pixelColor(x, y).alpha() > 0)
        assert nonwhite > 0, "nothing drawn"
        return f"{nonwhite} sampled pixels drawn"
    check("render layer", render)

    check("setCenter / setRotation / setScale / undo", lambda: (
        lyr.setCenter(QgsPointXY(lyr.center.x() + 100, lyr.center.y())),
        lyr.setRotation(15.5), lyr.setScale(2.0, 2.0),
        f"center={lyr.center} rot={lyr.rotation} scale={lyr.xScale},{lyr.yScale}")[-1])

    # drive each map tool with synthetic press / move / release
    def drive(tool, ctrl=False):
        canvas.setMapTool(tool)
        tool.setLayer(lyr)
        mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
        def ev(t, p):
            return QgsMapMouseEvent(canvas, t, QPoint(*p), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods)
        tool.canvasPressEvent(ev(QEvent.Type.MouseButtonPress, (400, 300)))
        tool.canvasMoveEvent(ev(QEvent.Type.MouseMove, (430, 320)))
        tool.canvasReleaseEvent(ev(QEvent.Type.MouseButtonRelease, (450, 330)))
        return f"center={lyr.center} rot={lyr.rotation:.2f} scale={lyr.xScale:.3f},{lyr.yScale:.3f}"

    for attr in ("moveTool", "rotateTool", "scaleTool", "adjustTool"):
        tool = getattr(plugin, attr, None)
        if tool is None:
            print("SKIP", attr, "(not found)")
            continue
        check(f"map tool {attr}", lambda t=tool: drive(t))
        check(f"map tool {attr} with Ctrl", lambda t=tool: drive(t, ctrl=True))
    check("2-point tool, first point pair", lambda: drive(plugin.georef2PTool))
    check("2-point tool, second point pair", lambda: drive(plugin.georef2PTool))
    check("transparency +/-", lambda: (plugin.increaseTransparency(), plugin.decreaseTransparency(), f"transparency={lyr.transparency}")[-1])
    check("rotation spin box", lambda: (plugin.spinBoxRotateValueChangeEvent(33.333), f"rot={lyr.rotation}")[-1])
    for name in ("moveRaster", "rotateRaster", "scaleRaster", "adjustRaster", "georef2PRaster"):
        check(f"toolbar action {name}", lambda n=name: (getattr(plugin, n)(), None)[-1])

    def export():
        lyr.setScale(2.0, 2.0); lyr.setRotation(10.0)   # undo the degenerate synthetic 2-point result
        out = os.path.join(PARENT, "out_georef.tif")
        cmd = ExportGeorefRasterCommand(iface)
        cmd.exportGeorefRaster(lyr, out, False, False)
        assert os.path.exists(out), "no export written"
        g = gdal.Open(out); gt = g.GetGeoTransform()
        return f"{g.RasterXSize}x{g.RasterYSize} gt={tuple(round(v, 2) for v in gt)}"
    check("export georeferenced raster (GeoTIFF)", export)

    def export_wf():
        out = os.path.join(PARENT, "out_world.png")
        ExportGeorefRasterCommand(iface).exportGeorefRaster(layers["png"], out, True, True)
        wf = [f for f in os.listdir(PARENT) if f.startswith("out_world") and f.lower().endswith(("w", ".wld", ".pgw"))]
        assert wf, "no world file written: " + str(os.listdir(PARENT))
        return "world file: " + ", ".join(wf)
    check("export world file only (PNG)", export_wf)

    if hasattr(plugin, "undo"):
        check("undo", lambda: (plugin.undo(), f"center={lyr.center}")[-1])

# south-orientated CRS (South African Lo31): the drag preview must sit on screen, under the red outline
def shadow_south_orientated():
    c = canvas
    c.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:2054"))
    lo = FreehandRasterGeoreferencerLayer(plugin, png, "lo31", QgsRectangle(-2000, 3302400, -1300, 3302800))
    QgsProject.instance().addMapLayer(lo)
    c.setExtent(lo.extent()); c.refresh()
    import types
    iface.activeLayer = lambda: lo
    tool = plugin.moveTool; c.setMapTool(tool); tool.setLayer(lo)
    def ev(t, pt):
        return QgsMapMouseEvent(c, t, QPoint(*pt), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tool.canvasPressEvent(ev(QEvent.Type.MouseButtonPress, (400, 300)))
    tool.canvasMoveEvent(ev(QEvent.Type.MouseMove, (450, 330)))
    sh, rb = tool.rasterShadow.pos(), tool.rubberBandExtent.pos()   # mid-drag
    tool.canvasReleaseEvent(ev(QEvent.Type.MouseButtonRelease, (450, 330)))
    assert abs(sh.x() - rb.x()) < 5 and abs(sh.y() - rb.y()) < 5, f"shadow at {sh} but outline at {rb}"
    return f"shadow {sh.x():.0f},{sh.y():.0f} vs outline {rb.x():.0f},{rb.y():.0f}"
check("drag preview on screen in south-orientated CRS (EPSG:2054)", shadow_south_orientated)

# dialogs build from .ui at runtime
from FreehandRasterGeoreferencer.freehandrastergeoreferencerdialog import FreehandRasterGeoreferencerDialog  # noqa: E402
from FreehandRasterGeoreferencer.exportgeorefrasterdialog import ExportGeorefRasterDialog  # noqa: E402
from FreehandRasterGeoreferencer.propertiesdialog import PropertiesDialog  # noqa: E402
from FreehandRasterGeoreferencer.loaderrordialog import LoadErrorDialog  # noqa: E402
check("Add-layer dialog builds", lambda: FreehandRasterGeoreferencerDialog() and None)
check("Export dialog builds", lambda: ExportGeorefRasterDialog() and None)
if lyr:
    check("Properties dialog builds", lambda: PropertiesDialog(lyr) and None)
check("Load-error dialog builds", lambda: LoadErrorDialog(tif) and None)

check("unload", plugin.unload)
print("\nFAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
