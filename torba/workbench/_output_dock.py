# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'output_dock.ui',
# licensing of 'output_dock.ui' applies.
#
# Created: Sat Oct 27 16:41:03 2018
#      by: pyside2-uic  running on PySide2 5.11.2
#
# WARNING! All changes made in this file will be lost!

from PySide2 import QtCore, QtGui, QtWidgets

class Ui_OutputDock(object):
    def setupUi(self, OutputDock):
        OutputDock.setObjectName("OutputDock")
        OutputDock.resize(700, 397)
        OutputDock.setFloating(False)
        OutputDock.setFeatures(QtWidgets.QDockWidget.AllDockWidgetFeatures)
        self.dockWidgetContents = QtWidgets.QWidget()
        self.dockWidgetContents.setObjectName("dockWidgetContents")
        self.horizontalLayout = QtWidgets.QHBoxLayout(self.dockWidgetContents)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.textEdit = QtWidgets.QTextEdit(self.dockWidgetContents)
        self.textEdit.setReadOnly(True)
        self.textEdit.setObjectName("textEdit")
        self.horizontalLayout.addWidget(self.textEdit)
        OutputDock.setWidget(self.dockWidgetContents)

        self.retranslateUi(OutputDock)
        QtCore.QMetaObject.connectSlotsByName(OutputDock)

    def retranslateUi(self, OutputDock):
        OutputDock.setWindowTitle(QtWidgets.QApplication.translate("OutputDock", "Output", None, -1))

