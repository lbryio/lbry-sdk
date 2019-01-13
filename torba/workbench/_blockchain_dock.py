# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'blockchain_dock.ui',
# licensing of 'blockchain_dock.ui' applies.
#
# Created: Sun Jan 13 02:56:21 2019
#      by: pyside2-uic  running on PySide2 5.12.0
#
# WARNING! All changes made in this file will be lost!

from PySide2 import QtCore, QtGui, QtWidgets

class Ui_BlockchainDock(object):
    def setupUi(self, BlockchainDock):
        BlockchainDock.setObjectName("BlockchainDock")
        BlockchainDock.resize(416, 167)
        BlockchainDock.setFloating(False)
        BlockchainDock.setFeatures(QtWidgets.QDockWidget.AllDockWidgetFeatures)
        self.dockWidgetContents = QtWidgets.QWidget()
        self.dockWidgetContents.setObjectName("dockWidgetContents")
        self.formLayout = QtWidgets.QFormLayout(self.dockWidgetContents)
        self.formLayout.setObjectName("formLayout")
        self.generate = QtWidgets.QPushButton(self.dockWidgetContents)
        self.generate.setObjectName("generate")
        self.formLayout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.generate)
        self.blocks = QtWidgets.QSpinBox(self.dockWidgetContents)
        self.blocks.setMinimum(1)
        self.blocks.setMaximum(9999)
        self.blocks.setProperty("value", 1)
        self.blocks.setObjectName("blocks")
        self.formLayout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.blocks)
        self.transfer = QtWidgets.QPushButton(self.dockWidgetContents)
        self.transfer.setObjectName("transfer")
        self.formLayout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.transfer)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.amount = QtWidgets.QDoubleSpinBox(self.dockWidgetContents)
        self.amount.setSuffix("")
        self.amount.setMaximum(9999.99)
        self.amount.setProperty("value", 10.0)
        self.amount.setObjectName("amount")
        self.horizontalLayout.addWidget(self.amount)
        self.to_label = QtWidgets.QLabel(self.dockWidgetContents)
        self.to_label.setObjectName("to_label")
        self.horizontalLayout.addWidget(self.to_label)
        self.address = QtWidgets.QLineEdit(self.dockWidgetContents)
        self.address.setObjectName("address")
        self.horizontalLayout.addWidget(self.address)
        self.formLayout.setLayout(1, QtWidgets.QFormLayout.FieldRole, self.horizontalLayout)
        self.invalidate = QtWidgets.QPushButton(self.dockWidgetContents)
        self.invalidate.setObjectName("invalidate")
        self.formLayout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.invalidate)
        self.block_hash = QtWidgets.QLineEdit(self.dockWidgetContents)
        self.block_hash.setObjectName("block_hash")
        self.formLayout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.block_hash)
        BlockchainDock.setWidget(self.dockWidgetContents)

        self.retranslateUi(BlockchainDock)
        QtCore.QMetaObject.connectSlotsByName(BlockchainDock)

    def retranslateUi(self, BlockchainDock):
        BlockchainDock.setWindowTitle(QtWidgets.QApplication.translate("BlockchainDock", "Blockchain", None, -1))
        self.generate.setText(QtWidgets.QApplication.translate("BlockchainDock", "generate", None, -1))
        self.blocks.setSuffix(QtWidgets.QApplication.translate("BlockchainDock", " block(s)", None, -1))
        self.transfer.setText(QtWidgets.QApplication.translate("BlockchainDock", "transfer", None, -1))
        self.to_label.setText(QtWidgets.QApplication.translate("BlockchainDock", "to", None, -1))
        self.address.setPlaceholderText(QtWidgets.QApplication.translate("BlockchainDock", "recipient address", None, -1))
        self.invalidate.setText(QtWidgets.QApplication.translate("BlockchainDock", "invalidate", None, -1))
        self.block_hash.setPlaceholderText(QtWidgets.QApplication.translate("BlockchainDock", "block hash", None, -1))

