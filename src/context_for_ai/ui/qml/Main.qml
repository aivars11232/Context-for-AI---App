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
    color: palette.window

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
            color: rootWindow.palette.alternateBase

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 18

                Label {
                    text: "Context for AI"
                    color: rootWindow.palette.windowText
                    font.pixelSize: 20
                    font.weight: Font.DemiBold
                }

                ItemDelegate {
                    objectName: "chatNavigationItem"
                    Layout.fillWidth: true
                    text: "Chat"
                    highlighted: shellFacade.route === "CHAT"
                    enabled: shellFacade.route !== "CHAT"
                    onClicked: shellFacade.navigate_to_chat()
                    Accessible.role: Accessible.Button
                    Accessible.name: "Chat"
                }

                ItemDelegate {
                    objectName: "contextInspectionNavigation"
                    Layout.fillWidth: true
                    text: "Context inspection"
                    visible: shellFacade.context_navigation_visible
                    highlighted: shellFacade.route === "CONTEXT_INSPECTION"
                    onClicked: shellFacade.navigate_to_context_inspection()
                    Accessible.id: "contextInspectionNavigation"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Context inspection"
                    Accessible.description: ""
                }

                ItemDelegate {
                    objectName: "memoryNavigation"
                    Layout.fillWidth: true
                    text: "Memory"
                    highlighted: shellFacade.route === "MEMORY"
                    onClicked: shellFacade.navigate_to_memory()
                    Accessible.id: "memoryNavigation"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Memory"
                }

                ItemDelegate {
                    objectName: "projectsNavigation"
                    Layout.fillWidth: true
                    text: "Projects"
                    highlighted: shellFacade.route === "PROJECTS"
                    onClicked: shellFacade.navigate_to_projects()
                    Accessible.id: "projectsNavigation"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Projects"
                }

                ItemDelegate {
                    objectName: "validationHistoryNavigation"
                    Layout.fillWidth: true
                    text: "Validation history"
                    highlighted: shellFacade.route === "VALIDATION_HISTORY"
                    onClicked: shellFacade.navigate_to_validation_history()
                    Accessible.id: "validationHistoryNavigation"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Validation history"
                }

                ItemDelegate {
                    objectName: "settingsNavigation"
                    Layout.fillWidth: true
                    text: "Settings"
                    highlighted: shellFacade.route === "SETTINGS"
                    onClicked: shellFacade.navigate_to_settings()
                    Accessible.id: "settingsNavigation"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Settings"
                }

                Item {
                    Layout.fillHeight: true
                }

                Label {
                    Layout.fillWidth: true
                    text: "Local desktop assistant"
                    color: rootWindow.palette.placeholderText
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: shellFacade.route === "CONTEXT_INSPECTION" ? 1
                          : shellFacade.route === "MEMORY" ? 2
                          : shellFacade.route === "PROJECTS" ? 3
                          : shellFacade.route === "VALIDATION_HISTORY" ? 4
                          : shellFacade.route === "SETTINGS" ? 5 : 0

            ChatPanel {
                objectName: "chatPanel"
                facade: shellFacade
            }

            ContextInspectionPage {
                objectName: "contextInspectionPage"
                facade: shellFacade
            }

            MemoryPage {
                objectName: "memoryPage"
                facade: shellFacade
            }

            ProjectsPage {
                objectName: "projectsPage"
                facade: shellFacade
            }

            ValidationHistoryPage {
                objectName: "validationHistoryPage"
                facade: shellFacade
            }

            SettingsPage {
                objectName: "settingsPage"
                facade: shellFacade
            }
        }
    }
}
