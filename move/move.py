# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Move
                                 A QGIS plugin
 The Move plugin links MobilityDB to QGIS to visualize moving objects
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2021-03-24
        git sha              : $Format:%H$
        copyright            : (C) 2021 by MobilityDB
        email                : maxime.schoemans@ulb.be
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtCore import QTranslator
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import Qgis
from qgis.core import QgsApplication
from qgis.core import QgsDataSourceUri
from qgis.core import QgsGeometryGeneratorSymbolLayer
from qgis.core import QgsMessageLog
from qgis.core import QgsProject
from qgis.core import QgsTask
from qgis.core import QgsVectorLayer
from qgis.core import QgsWkbTypes

# Initialize Qt resources from file resources.py
from .resources import *

# Import the code for the DockWidget
import os.path
import psycopg2
import uuid

from .move_dockwidget import MoveDockWidget
from .move_query import MoveQuery
from .move_task import MoveGeomTask
from .move_task import MoveTTask


class Move:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        self.tm = QgsApplication.taskManager()

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(self.plugin_dir, 'i18n',
                                   'Move_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Move')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'Move')
        self.toolbar.setObjectName(u'Move')

        #print "** INITIALIZING Move"

        self.pluginIsActive = False
        self.dockwidget = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('Move', message)

    def add_action(self,
                   icon_path,
                   text,
                   callback,
                   enabled_flag=True,
                   add_to_menu=True,
                   add_to_toolbar=True,
                   status_tip=None,
                   whats_this=None,
                   parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToDatabaseMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/move/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Open Move Interface'),
            callback=self.run,
            parent=self.iface.mainWindow())

    #--------------------------------------------------------------------------

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""

        #print "** CLOSING Move"

        # disconnects
        self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)
        self.dockwidget.combo_database.activated[str].disconnect(
            self.onDbChanged)
        self.dockwidget.button_execute.clicked.disconnect(self.execute)
        self.dockwidget.button_refresh.clicked.disconnect(self.refresh)

        # remove this statement if dockwidget is to remain
        # for reuse if plugin is reopened
        # Commented next statement since it causes QGIS crashe
        # when closing the docked window:
        # self.dockwidget = None

        self.pluginIsActive = False

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""

        #print "** UNLOAD Move"

        for action in self.actions:
            self.iface.removePluginDatabaseMenu(self.tr(u'&Move'), action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    #--------------------------------------------------------------------------

    def run(self):
        """Run method that loads and starts the plugin"""

        if not self.pluginIsActive:
            self.pluginIsActive = True

            #print "** STARTING Move"

            # dockwidget may not exist if:
            #    first run of plugin
            #    removed on close (see self.onClosePlugin method)
            if self.dockwidget == None:
                # Create the dockwidget (after translation) and keep reference
                self.dockwidget = MoveDockWidget()

            # connects
            self.dockwidget.closingPlugin.connect(self.onClosePlugin)
            self.dockwidget.combo_database.activated[str].connect(
                self.onDbChanged)
            self.dockwidget.button_execute.clicked.connect(self.execute)
            self.dockwidget.button_refresh.clicked.connect(self.refresh)

            self.project_title = QgsProject.instance().title().lower().replace(" ", "_")
            self.setDatabaseComboBox()

            # show the dockwidget
            # TODO: fix to allow choice of dock location
            self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.dockwidget)
            self.dockwidget.show()

    def setDatabaseComboBox(self):
        self.dockwidget.combo_database.clear()
        s = QSettings()
        s.beginGroup("PostgreSQL/connections")
        db_names = s.childGroups()
        self.db_params = dict()
        if len(db_names) == 0:
            self.log("No Database Connections Available")
            self.set_execute_enabled(False)
        else:
            for name in db_names:
                self.db_params[name] = {
                    'host': s.value(f"{name}/host"),
                    'port': s.value(f"{name}/port"),
                    'database': s.value(f"{name}/database"),
                    'username': s.value(f"{name}/username"),
                    'password': s.value(f"{name}/password")
                }
                self.dockwidget.combo_database.addItem(name)
            self.onDbChanged(db_names[0])
            self.set_execute_enabled(True)
        s.endGroup()

    @property
    def db(self):
        return self.db_params[self.current_db]

    def onDbChanged(self, db_name):
        self.current_db = db_name
        # TODO: Maybe display textboxes for username and password

    def get_layer_view_names(self):
        view_names = []
        for layer in QgsProject.instance().mapLayers().values():
            view_name = layer.customProperty('move/view_name')
            if view_name is not None:
                view_names.append(view_name)
        view_name_strings = [f"'{name}'" for name in view_names]
        view_names_string = ", ".join(view_name_strings)
        return view_names_string

    # Refresh materialized views of existing layers
    def refresh(self):
        self.dockwidget.button_refresh.setEnabled(False)
        layer_name = self.iface.activeLayer().customProperty('move/view_name')
        select_sql = f"refresh materialized view {layer_name};"

        def run(task):
            with psycopg2.connect(
                    host=self.db['host'],
                    port=self.db['port'],
                    dbname=self.db['database'],
                    user=self.db['username'],
                    password=self.db['password']) as conn:
                with conn.cursor() as cur:
                    cur.execute(select_sql)
                    conn.commit()

        def completed(exception):
            self.dockwidget.button_refresh.setEnabled(True)
            if exception is not None:
                self.log(f"Exception: {exception}")

        if layer_name is not None:
            task = QgsTask.fromFunction(
                'Move: Refresh Active Layer', run, on_finished=completed)
            self.tm.addTask(task)
        else:
            self.dockwidget.button_refresh.setEnabled(True)

    # Drop unused materialized views
    def clean(self):
        select_sql = f"""
            select 'drop materialized view ' || relname || ';'
            from pg_class
            where relkind = 'm'
            and relname like 'move@_{self.project_title}@_%' escape '@'
        """

        view_names = self.get_layer_view_names()
        if view_names:
            select_sql += f" and relname not in ({view_names})"

        try:
            with psycopg2.connect(
                    host=self.db['host'],
                    port=self.db['port'],
                    dbname=self.db['database'],
                    user=self.db['username'],
                    password=self.db['password']) as conn:
                with conn.cursor() as cur:
                    cur.execute(select_sql)
                    drop_sqls = cur.fetchall()
                    for drop_sql, in drop_sqls:
                        cur.execute(drop_sql)
                    conn.commit()
        except psycopg2.Error as e:
            pass

    def set_execute_enabled(self, enabled=True):
        self.dockwidget.button_execute.setEnabled(enabled)
        self.dockwidget.input_text.setReadOnly(not enabled)

    # Execute current query
    def execute(self):
        self.clean()
        self.set_execute_enabled(False)
        raw_sql = self.dockwidget.input_text.toPlainText()
        if raw_sql:
            query = MoveQuery(raw_sql)
            if not query.is_valid:
                self.log(f"Invalid Query: {query}")
            else:
                self.log(f"Running Query: {query}")
                self.run_query(query)
        self.set_execute_enabled(True)

    def run_query(self, query):
        if not query.resolve_types(self.db):
            self.log("Error: " + query.error_msg)
            return
        self.log("Query return types: " + ", ".join(query.column_types))
        if query.has_geom_columns():
            task = MoveGeomTask("Move: Creating geom view", query,
                                self.project_title, self.db,
                                self.add_geom_layers, self.raise_error)
            self.tm.addTask(task)
        if query.has_temp_columns():
            temp_cols = query.temp_cols()
            for col in temp_cols:
                if query.column_types[col] == 'tgeometry':
                    task = MoveTTask(f"Move: Creating tgeom view {col}", query,
                                     self.project_title, self.db, col,
                                     self.add_tgeom_layer, self.raise_error)
                else:
                    task = MoveTTask(f"Move: Creating tpoint view {col}",
                                     query, self.project_title, self.db, col,
                                     self.add_tpoint_layer, self.raise_error)
                self.tm.addTask(task)

    def raise_error(self, msg):
        self.log("Error: " + msg)

    def add_geom_layers(self, db, query, params):
        view_name = params['view_name']
        col_names = params['col_names']
        srids = params['srids']
        geom_types = params['geom_types']
        for i in range(len(col_names)):
            col_types = geom_types[i]
            for col_type in col_types:
                uri = QgsDataSourceUri()
                uri.setConnection(db['host'], db['port'], db['database'],
                                  db['username'], db['password'],
                                  QgsDataSourceUri.SslDisable)
                uri.setDataSource("public", view_name, col_names[i], "", "id")
                uri.setSrid(str(srids[i]))
                uri.setWkbType(QgsWkbTypes.parseType(col_type))
                layer_name = col_names[i]
                layer = self.iface.addVectorLayer(uri.uri(), layer_name,
                                                  "postgres")
                if not layer or not layer.isValid():
                    self.msg("Layer failed to load!")
                else:
                    layer.setCustomProperty('move/view_name', view_name)
                    layer.setCustomProperty('move/sql', query.raw_sql)

    def add_tpoint_layer(self, db, query, params):
        view_name = params['view_name']
        uri = QgsDataSourceUri()
        uri.setConnection(db['host'], db['port'], db['database'],
                          db['username'], db['password'],
                          QgsDataSourceUri.SslDisable)
        uri.setDataSource("public", view_name, "geom", "", "id")
        uri.setSrid(str(params['srid']))
        uri.setWkbType(QgsWkbTypes.LineStringM)
        layer_name = query.column_names[params['col_id']]
        layer = self.iface.addVectorLayer(uri.uri(), layer_name, "postgres")
        if not layer or not layer.isValid():
            self.msg("Layer failed to load!")
        else:
            layer.setCustomProperty('move/view_name', view_name)
            layer.setCustomProperty('move/sql', query.raw_sql)
            layer.temporalProperties().setIsActive(True)
            pointGeneratorLayer = QgsGeometryGeneratorSymbolLayer.create({
                'SymbolType':
                'Marker',
                'geometryModifier':
                'line_interpolate_point(\n  $geometry,\n  1.0 * (\n    ( epoch(@map_end_time)/1000 )\n    - m(start_point($geometry))\n  ) / (\n    m(end_point($geometry))\n    - m(start_point($geometry))\n  )\n  * length($geometry)\n) '
            })
            layer.renderer().symbol().changeSymbolLayer(0, pointGeneratorLayer)
            layer.triggerRepaint()
            self.iface.layerTreeView().refreshLayerSymbology(layer.id())

    def add_tgeom_layer(self, db, query, params):
        view_name = params['view_name']
        uri = QgsDataSourceUri()
        uri.setConnection(db['host'], db['port'], db['database'],
                          db['username'], db['password'],
                          QgsDataSourceUri.SslDisable)
        uri.setDataSource("public", view_name, "geom")
        uri.setKeyColumn("id")
        uri.setSrid(str(params['srid']))
        uri.setWkbType(QgsWkbTypes.Polygon)
        layer_name = query.column_names[params['col_id']]
        layer = self.iface.addVectorLayer(uri.uri(), layer_name, "postgres")
        if not layer or not layer.isValid():
            self.log(
                f"Failed to load layer {layer_name} from view {view_name}")
        else:
            layer.setCustomProperty('move/view_name', view_name)
            layer.setCustomProperty('move/sql', query.raw_sql)
            layer.temporalProperties().setIsActive(True)

    def msg(self, msg):
        self.iface.messageBar().pushMessage(msg, level=Qgis.Info, duration=3)

    def log(self, msg):
        QgsMessageLog.logMessage(msg, 'Move', level=Qgis.Info)