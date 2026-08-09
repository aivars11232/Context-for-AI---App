import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: rootWindow
    objectName: "contextForAiRoot"
    visible: true
    width: 960
    height: 680
    minimumWidth: 720
    minimumHeight: 520
    title: "Context for AI"
    color: "#f4f6f8"

    property bool shutdownAccepted: false

    onClosing: function(close) {
        if (!shutdownAccepted) {
            shellFacade.request_shutdown()
            close.accepted = shutdownAccepted
        }
    }

    Connections {
        target: shellFacade

        function onShutdownReady() {
            rootWindow.shutdownAccepted = true
            rootWindow.close()
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 210
            Layout.fillHeight: true
            color: "#172033"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 18

                Label {
                    text: "Context for AI"
                    color: "#ffffff"
                    font.pixelSize: 20
                    font.weight: Font.DemiBold
                }

                ItemDelegate {
                    objectName: "chatNavigationItem"
                    Layout.fillWidth: true
                    text: "Chat"
                    highlighted: true
                    enabled: false
                    Accessible.name: "Chat"
                }

                Item {
                    Layout.fillHeight: true
                }

                Label {
                    Layout.fillWidth: true
                    text: "Local desktop assistant"
                    color: "#aeb9cb"
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }
            }
        }

        ChatPanel {
            objectName: "chatPanel"
            Layout.fillWidth: true
            Layout.fillHeight: true
            facade: shellFacade
        }
    }
}
