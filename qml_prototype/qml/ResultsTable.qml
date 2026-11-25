import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: table
    required property var controller
    readonly property var columns: controller.columns
    readonly property var shownRows: controller.visibleRows
    readonly property real minimumWidth: columns.reduce((sum, col) => sum + col.minWidth, 0)
    readonly property real tableWidth: Math.max(minimumWidth, width)
    spacing: 0

    function columnWidth(column) {
        return tableWidth * column.minWidth / minimumWidth
    }

    Connections {
        target: table.controller
        function onSourceChanged() {
            resultList.contentX = 0
            resultList.positionViewAtBeginning()
        }
        function onOrderChanged() { resultList.positionViewAtBeginning() }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 36
        color: "#1e293b"
        clip: true
        Row {
            x: -resultList.contentX
            height: parent.height
            Repeater {
                model: table.columns
                delegate: AbstractButton {
                    id: header
                    required property var modelData
                    objectName: "column_" + modelData.key
                    width: table.columnWidth(modelData)
                    height: 36
                    leftPadding: 10
                    rightPadding: 8
                    hoverEnabled: true
                    text: modelData.label + (table.controller.sortKey === modelData.key ?
                        (table.controller.sortDescending ? "  ▼" : "  ▲") : "")
                    contentItem: Text {
                        text: header.text
                        textFormat: Text.PlainText
                        color: "#67e8f9"
                        font.bold: true
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle { color: header.hovered ? "#334155" : "transparent" }
                    onClicked: table.controller.sortBy(modelData.key)
                }
            }
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        ListView {
            id: resultList
            objectName: "resultList"
            anchors.fill: parent
            clip: true
            contentWidth: table.tableWidth
            flickableDirection: Flickable.AutoFlickDirection
            boundsBehavior: Flickable.StopAtBounds
            model: table.shownRows
            ScrollBar.horizontal: ScrollBar { policy: resultList.contentWidth > resultList.width ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                id: resultRow
                required property int index
                required property var modelData
                width: table.tableWidth
                height: 38
                color: index % 2 === 0 ? "#0f172a" : "#162032"
                Row {
                    height: parent.height
                    Repeater {
                        model: table.columns
                        delegate: Item {
                            id: cell
                            required property var modelData
                            readonly property string value: String(resultRow.modelData[modelData.key] ?? "")
                            readonly property bool isLink: modelData.key === "url" && /^https?:\/\//i.test(value)
                            width: table.columnWidth(modelData)
                            height: resultRow.height
                            Text {
                                id: cellText
                                anchors.fill: parent
                                leftPadding: 10
                                rightPadding: 8
                                verticalAlignment: Text.AlignVCenter
                                text: cell.value
                                textFormat: Text.PlainText
                                color: cell.isLink ? "#7dd3fc" : "#e2e8f0"
                                font.pixelSize: 12
                                elide: Text.ElideRight
                                maximumLineCount: 1
                            }
                            HoverHandler {
                                id: hover
                                cursorShape: cell.isLink ? Qt.PointingHandCursor : Qt.ArrowCursor
                            }
                            TapHandler {
                                enabled: cell.isLink
                                onTapped: Qt.openUrlExternally(cell.value)
                            }
                            ToolTip.visible: hover.hovered && cellText.truncated
                            ToolTip.delay: 450
                            ToolTip.text: "<qt>" + cell.value.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                                .replace(/>/g, "&gt;").replace(/\n/g, "<br>") + "</qt>"
                        }
                    }
                }
            }
        }
        Label {
            anchors.centerIn: parent
            visible: resultList.count === 0
            text: table.controller.rows.length ? "Tidak ada hasil yang cocok dengan filter." : "Belum ada hasil untuk sumber ini."
            color: "#94a3b8"
        }
    }
}
